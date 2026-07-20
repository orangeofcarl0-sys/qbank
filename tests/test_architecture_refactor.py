"""Architecture, read-only index, packaged-resource, and typed-boundary regressions."""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from qbank.bootstrap import create_question_service
from qbank.context import ProjectContext
from qbank.diagnostics import doctor, project_status
from qbank.errors import DataValidationError
from qbank.init_resources import initialization_resources
from qbank.models import Paper
from qbank.operations import add_question
from qbank.papers import validate_paper
from qbank.project import initialize_project
from qbank.repository import MarkdownQuestionRepository
from qbank.search_index import (
    INDEX_COLUMNS,
    IndexDocument,
    SQLiteSearchIndex,
    last_updated,
    search,
)
from qbank.storage import render_question
from qbank.transaction import MutationTransaction
from qbank.validation import validate_repository


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_missing_index_readers_are_zero_write(project: tuple[Path, Any]) -> None:
    root, config = project
    (root / ".qbank/index.sqlite").unlink()
    before = _tree_digest(root)

    status = project_status(root, config)
    report = doctor(root, config)
    assert status.index_dirty is True
    assert next(item for item in report.checks if item.name == "index").status == "FAIL"
    with pytest.raises(DataValidationError, match="index_unavailable"):
        search(root, config, "anything")
    assert last_updated(root, config) is None

    assert _tree_digest(root) == before
    assert not (root / ".qbank/index.dirty").exists()


def test_search_rejects_stale_index_without_writing(
    project: tuple[Path, Any],
    question: Any,
) -> None:
    root, config = project
    add_question(root, config, question)
    source = root / f"questions/{question.subject}/{question.id}.md"
    changed = question.model_copy(update={"title": "Externally changed"})
    source.write_text(render_question(changed), encoding="utf-8")
    before = _tree_digest(root)

    context = ProjectContext.from_config(root, config)
    with pytest.raises(DataValidationError, match="index_stale"):
        create_question_service(context).search_questions("Michelson")

    assert _tree_digest(root) == before


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("clean", "clean"),
        ("missing", "missing"),
        ("corrupt", "corrupt"),
        ("dirty", "dirty"),
        ("stale", "stale"),
        ("disabled", "disabled"),
    ],
)
def test_index_health_states(
    project: tuple[Path, Any],
    question: Any,
    state: str,
    expected: str,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    index = SQLiteSearchIndex(context)
    if state == "missing":
        index.path.unlink()
    elif state == "corrupt":
        index.path.write_bytes(b"not sqlite")
    elif state == "dirty":
        index.mark_dirty("test")
    elif state == "stale":
        destination = root / "questions/optics/OPT-INT-0001.md"
        destination.write_text(render_question(question), encoding="utf-8")
    elif state == "disabled":
        disabled = config.model_copy(
            update={"index": config.index.model_copy(update={"enabled": False})}
        )
        context = ProjectContext.from_config(root, disabled)
        index = SQLiteSearchIndex(context)

    snapshot = MarkdownQuestionRepository(context).scan()
    health = index.health(snapshot)
    assert health.state == expected
    assert health.dirty is (expected not in {"clean", "disabled"})


def test_one_snapshot_is_reused_by_validation_paper_and_index(
    project: tuple[Path, Any],
    question: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    add_question(root, config, question)
    context = ProjectContext.from_config(root, config)
    repository = MarkdownQuestionRepository(context)

    from qbank import repository as repository_module

    original = repository_module.parse_question_text
    calls = 0

    def counting_parser(text: str) -> Any:
        nonlocal calls
        calls += 1
        return original(text)

    monkeypatch.setattr(repository_module, "parse_question_text", counting_parser)
    snapshot = repository.scan()
    assert calls == len(snapshot.paths) == 1

    validation = validate_repository(root, config, snapshot=snapshot)
    paper = Paper.model_validate(
        {
            "schema_version": "1.0",
            "title": "Snapshot paper",
            "sections": [
                {
                    "title": "Section",
                    "questions": [{"id": question.id, "score": 1}],
                }
            ],
        }
    )
    paper_report = validate_paper(root, config, paper, snapshot=snapshot)
    health = SQLiteSearchIndex(context).health(snapshot)
    assert validation.ok and paper_report.ok and health.state == "clean"
    assert calls == 1


def test_index_document_is_the_shared_projection(
    project: tuple[Path, Any],
    question: Any,
) -> None:
    root, config = project
    add_question(root, config, question)
    context = ProjectContext.from_config(root, config)
    projection = IndexDocument.from_question(question)
    index = SQLiteSearchIndex(context)

    assert IndexDocument.columns() == INDEX_COLUMNS
    assert len(projection.values()) == len(INDEX_COLUMNS)
    assert index.documents() == {question.id: projection.comparable()}
    assert index.health(MarkdownQuestionRepository(context).scan()).state == "clean"


def test_rollback_failure_does_not_mask_commit_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = tmp_path / "existing.md"
    existing.write_text("before", encoding="utf-8")
    pending = tmp_path / "pending.md"
    transaction = MutationTransaction()
    transaction.write(existing, "changed")
    transaction.write(pending, "new")

    from qbank import transaction as transaction_module

    original_write = transaction_module.atomic_write_text

    class CommitFailure(OSError):
        pass

    calls = 0

    def fail_second_write(path: Path, text: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CommitFailure("authoritative commit failed")
        original_write(path, text)

    def fail_rollback(path: Path, content: bytes) -> None:
        del path, content
        raise OSError("rollback storage failed")

    monkeypatch.setattr(transaction_module, "atomic_write_text", fail_second_write)
    monkeypatch.setattr(transaction_module, "atomic_write_bytes", fail_rollback)
    with pytest.raises(CommitFailure, match="authoritative commit failed") as captured:
        transaction.commit()
    assert any("rollback failed" in note for note in captured.value.__notes__)


def test_package_resources_match_mirrors_and_init_output(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    mirrors = {
        "AGENTS.md": "AGENTS.md",
        ".agents/skills/qbank/SKILL.md": ".agents/skills/qbank/SKILL.md",
        ".agents/skills/qbank/agents/openai.yaml": (".agents/skills/qbank/agents/openai.yaml"),
        ".agents/skills/qbank/references/workflows.md": (
            ".agents/skills/qbank/references/workflows.md"
        ),
        ".agents/skills/qbank/references/command-reference.md": (
            ".agents/skills/qbank/references/command-reference.md"
        ),
        ".agents/skills/qbank/references/examples.md": (
            ".agents/skills/qbank/references/examples.md"
        ),
        "templates/paper.md.j2": "templates/paper.md.j2",
        "templates/paper.html.j2": "templates/paper.html.j2",
        "papers/demo-paper.yaml": "papers/demo-paper.yaml",
    }
    initialized = {
        resource.destination.as_posix(): resource.text() for resource in initialization_resources()
    }
    for destination, visible in mirrors.items():
        assert initialized[destination] == (repository_root / visible).read_text(encoding="utf-8")

    root = initialize_project(tmp_path / "initialized")
    for resource in initialization_resources():
        assert (
            root.joinpath(*resource.destination.parts).read_text(encoding="utf-8")
            == resource.text()
        )


def test_development_lock_covers_declared_dev_and_build_requirements() -> None:
    repository_root = Path(__file__).parents[1]
    project = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = [
        *project["build-system"]["requires"],
        *project["project"]["dependencies"],
        *project["project"]["optional-dependencies"]["dev"],
    ]
    locked: dict[str, Version] = {}
    for line in (
        (repository_root / "requirements-dev.lock").read_text(encoding="utf-8").splitlines()
    ):
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        requirement = Requirement(candidate)
        pinned = next(
            specifier.version for specifier in requirement.specifier if specifier.operator == "=="
        )
        locked[canonicalize_name(requirement.name)] = Version(pinned)
    for raw in declared:
        requirement = Requirement(raw)
        name = canonicalize_name(requirement.name)
        assert name in locked
        assert locked[name] in requirement.specifier


def _package_modules(source_root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        parts = relative.with_suffix("").parts
        name = (
            ".".join(("qbank", *parts[:-1]))
            if parts[-1] == "__init__"
            else ".".join(("qbank", *parts))
        )
        modules[name] = path
    return modules


def _imports(path: Path, known: set[str]) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            if node.module == "qbank":
                names.extend(f"qbank.{alias.name}" for alias in node.names)
        for name in names:
            candidate = name
            while candidate:
                if candidate in known:
                    result.add(candidate)
                    break
                candidate = candidate.rpartition(".")[0]
    return result


def test_internal_import_graph_is_acyclic_and_layered() -> None:
    source_root = Path(__file__).parents[1] / "src/qbank"
    modules = _package_modules(source_root)
    graph = {module: _imports(path, set(modules)) for module, path in modules.items()}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str, trail: tuple[str, ...] = ()) -> None:
        if module in visiting:
            raise AssertionError("import cycle: " + " -> ".join((*trail, module)))
        if module in visited:
            return
        visiting.add(module)
        for dependency in graph[module]:
            visit(dependency, (*trail, module))
        visiting.remove(module)
        visited.add(module)

    for module in graph:
        visit(module)

    forbidden = (
        "qbank.cli",
        "qbank.commands",
        "qbank.operations",
        "qbank.papers",
        "qbank.exporters",
        "qbank.preview",
        "qbank.diagnostics",
        "qbank.search_index",
    )
    domain_modules = {
        module
        for module in modules
        if module == "qbank.context"
        or module == "qbank.question_layout"
        or module.startswith("qbank.models")
    }
    violations = {
        module: sorted(
            dependency for dependency in graph[module] if dependency.startswith(forbidden)
        )
        for module in domain_modules
    }
    assert not {module: deps for module, deps in violations.items() if deps}


def test_built_wheel_initializes_outside_source_tree(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    wheel_dir = tmp_path / "wheel"
    target = tmp_path / "installed"
    outside = tmp_path / "outside"
    wheel_dir.mkdir()
    target.mkdir()
    outside.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("qbank-*.whl"))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            str(wheel),
            "--no-deps",
            "--target",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    script = (
        "from pathlib import Path; import qbank; "
        "from qbank.project import initialize_project; "
        f"target=Path({str(target)!r}).resolve(); "
        "assert Path(qbank.__file__).resolve().is_relative_to(target); "
        "root=initialize_project(Path('bank')); "
        "assert (root/'templates/paper.md.j2').is_file(); "
        "assert (root/'assets/images/interference.svg').is_file(); "
        "assert (root/'AGENTS.md').is_file(); "
        "assert (root/'.agents/skills/qbank/SKILL.md').is_file()"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(target)
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=outside,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    module_help = subprocess.run(
        [sys.executable, "-m", "qbank", "--help"],
        cwd=outside,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Usage:" in module_help.stdout
    candidates = [
        target / "Scripts" / "qbank.exe",
        target / "bin" / "qbank.exe",
        target / "bin" / "qbank",
    ]
    console_script = next((candidate for candidate in candidates if candidate.is_file()), None)
    assert console_script is not None
    console_help = subprocess.run(
        [str(console_script), "--help"],
        cwd=outside,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Usage:" in console_help.stdout
