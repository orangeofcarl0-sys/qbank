"""End-to-end coverage for the lightweight digitize and deliver Skills."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from qbank.context import ProjectContext
from qbank.mcp.adapter import QbankMcpAdapter
from qbank.models import (
    AssetIngestPrepareRequest,
    AssetPackage,
    IngestPrepareRequest,
    QueryFilters,
    Question,
)
from qbank.yaml_io import dump_yaml, load_yaml

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "workflows" / "lightweight"


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _digitize_module() -> ModuleType:
    return _module(
        "qbank_digitize_check_exchange_test",
        ROOT / ".agents/skills/qbank-digitize/scripts/check_exchange.py",
    )


def _deliver_module() -> ModuleType:
    return _module(
        "qbank_deliver_build_test",
        ROOT / ".agents/skills/qbank-deliver/scripts/build_delivery.py",
    )


def _demo_module() -> ModuleType:
    return _module(
        "qbank_lightweight_demo_test",
        EXAMPLE / "run_demo.py",
    )


def _questions(path: Path) -> list[Question]:
    return [
        Question.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_public_digitization_exchange_is_valid_and_read_only() -> None:
    workspace = EXAMPLE / "digitize"
    before = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    result = _digitize_module().check(workspace)
    after = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert result == {
        "ok": True,
        "workspace": str(workspace.resolve()),
        "questions": 2,
        "asset_packages": 1,
        "review_items": 1,
        "diagnostics": [],
    }
    assert after == before


def test_digitization_exchange_rejects_cross_project_asset_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "digitize"
    shutil.copytree(EXAMPLE / "digitize", workspace)
    package_path = next((workspace / "assets/packages").glob("*.json"))
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["representations"][0].pop("base64")
    package["representations"][0]["path"] = "mineru/crop.png"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    result = _digitize_module().check(workspace)

    assert not result["ok"]
    assert "path_backed_asset" in {item["code"] for item in result["diagnostics"]}


def _import_example(adapter: QbankMcpAdapter) -> list[Question]:
    digitize = EXAMPLE / "digitize"
    assert adapter.schema_get("question")["title"] == "Question"
    package = AssetPackage.model_validate_json(
        next((digitize / "assets/packages").glob("*.json")).read_text(encoding="utf-8")
    )
    asset = adapter.asset_ingest_prepare(AssetIngestPrepareRequest(package=package))
    assert asset.committable
    adapter.operation_commit(asset.operation_id, asset.repository_revision)
    questions = _questions(digitize / "questions.jsonl")
    ingest = adapter.ingest_prepare(IngestPrepareRequest(questions=questions))
    assert ingest.committable
    adapter.operation_commit(ingest.operation_id, ingest.repository_revision)
    assert adapter.question_validate().ok
    return questions


def _delivery_workspace(
    tmp_path: Path,
    adapter: QbankMcpAdapter,
    questions: list[Question],
    *,
    variant: str = "solution",
) -> Path:
    workspace = tmp_path / f"delivery-{variant}"
    (workspace / "snapshot/assets/DEMO-FIG-0001").mkdir(parents=True)
    candidates = adapter.question_search(
        filters=QueryFilters(subject="synthetic"),
        limit=20,
    )
    assert {item.id for item in candidates.items} == {"DEMO-FIG-0001", "DEMO-MATH-0001"}
    current = [adapter.question_get(question.id) for question in questions]
    (workspace / "snapshot/questions.jsonl").write_text(
        "".join(question.model_dump_json() + "\n" for question in current),
        encoding="utf-8",
    )
    asset = adapter.asset_get("DEMO-FIG-0001", "figure-1")
    (workspace / "snapshot/assets/DEMO-FIG-0001/figure-1.json").write_text(
        asset.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(EXAMPLE / "deliver/content.tex", workspace / "content.tex")
    selection = {
        "version": "1",
        "repository_revision": adapter.revision(),
        "template": "qbank-zh-exam-v1",
        "variant": variant,
        "document": {
            "title": "qbank 合成示例试卷",
            "subject": "示例学科",
            "date": "2026-07-26",
            "duration_minutes": 30,
        },
        "questions": [
            {"id": "DEMO-MATH-0001", "score": 10, "assets": {}},
            {
                "id": "DEMO-FIG-0001",
                "score": 10,
                "assets": {"figure-1": "render-png"},
            },
        ],
    }
    (workspace / "selection.yaml").write_text(
        dump_yaml(selection) + "\n",
        encoding="utf-8",
    )
    return workspace


def test_mcp_exchange_to_delivery_snapshot_is_reproducible(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    questions = _import_example(adapter)
    workspace = _delivery_workspace(tmp_path, adapter, questions)
    revision = adapter.revision()

    result = _deliver_module().build(workspace, root, compile_pdf=False)

    assert result["ok"]
    assert result["repository_revision"] == revision
    assert result["questions"] == ["DEMO-MATH-0001", "DEMO-FIG-0001"]
    assert result["total_score"] == 20
    assert {item["code"] for item in result["warnings"]} == {
        "draft_question",
        "missing_answer",
        "missing_rubric",
        "missing_solution",
    }
    assert result["assets"][0]["asset_id"] == "figure-1"
    assert result["pdf_sha256"] is None
    assert (workspace / "output/solution/build-summary.json").is_file()
    selection = load_yaml_for_test(workspace / "selection.yaml")
    selection["variant"] = "answer"
    (workspace / "selection.yaml").write_text(
        dump_yaml(selection) + "\n",
        encoding="utf-8",
    )
    _deliver_module().build(workspace, root, compile_pdf=False)
    assert (workspace / "output/answer/build-summary.json").is_file()
    assert (workspace / "output/solution/build-summary.json").is_file()
    assert adapter.revision() == revision


def test_delivery_validate_only_does_not_write_workspace(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    questions = _import_example(adapter)
    workspace = _delivery_workspace(tmp_path, adapter, questions)
    before = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    result = _deliver_module().build(
        workspace,
        root,
        compile_pdf=False,
        commit_output=False,
    )

    after = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert result["ok"]
    assert before == after
    assert not (workspace / "output").exists()


def test_public_demo_runs_the_full_adapter_flow_without_tex(tmp_path: Path) -> None:
    destination = tmp_path / "public-demo"

    result = _demo_module().run(destination, compile_pdf=False)

    assert result["ok"]
    assert result["summary"]["questions"] == list(QUESTION_IDS_FOR_TEST)
    assert (destination / "bank" / "qbank.yaml").is_file()
    assert (destination / "delivery" / "output" / "solution" / "build-summary.json").is_file()


QUESTION_IDS_FOR_TEST = ("DEMO-MATH-0001", "DEMO-FIG-0001")


def test_delivery_rejects_revision_drift_and_forbidden_tex(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    questions = _import_example(adapter)
    workspace = _delivery_workspace(tmp_path, adapter, questions)
    module = _deliver_module()
    content = workspace / "content.tex"
    content.write_text(
        content.read_text(encoding="utf-8") + "\n\\input{outside.tex}\n",
        encoding="utf-8",
    )
    with pytest.raises(module.DeliveryError, match="forbidden command"):
        module.build(workspace, root, compile_pdf=False)

    content.write_text(
        content.read_text(encoding="utf-8").replace(
            "\\input{outside.tex}",
            "\\in^^70ut{outside.tex}",
        ),
        encoding="utf-8",
    )
    with pytest.raises(module.DeliveryError, match="forbidden TeX encoding"):
        module.build(workspace, root, compile_pdf=False)

    safe_content = (EXAMPLE / "deliver/content.tex").read_text(encoding="utf-8")
    content.write_text(
        safe_content + "\n\\XeTeXpicfile outside.pdf\n",
        encoding="utf-8",
    )
    with pytest.raises(module.DeliveryError, match="unsupported commands"):
        module.build(workspace, root, compile_pdf=False)

    content.write_text(
        safe_content + "\n% an untrusted TeX comment\n",
        encoding="utf-8",
    )
    with pytest.raises(module.DeliveryError, match="unescaped TeX comment"):
        module.build(workspace, root, compile_pdf=False)

    shutil.copy2(EXAMPLE / "deliver/content.tex", content)
    (root / "papers/revision-change.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(module.DeliveryError, match="repository revision changed"):
        module.build(workspace, root, compile_pdf=False)


def test_delivery_rejects_linked_output_root(
    project: tuple[Path, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    questions = _import_example(adapter)
    workspace = _delivery_workspace(tmp_path, adapter, questions)
    module = _deliver_module()
    output_root = workspace.resolve() / "output"
    original = module._is_reparse_point

    def reports_link(path: Path) -> bool:
        return path == output_root or original(path)

    monkeypatch.setattr(module, "_is_reparse_point", reports_link)

    with pytest.raises(module.DeliveryError, match="link or reparse point"):
        module.build(workspace, root, compile_pdf=False)


def test_delivery_rejects_changed_asset_content(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    questions = _import_example(adapter)
    workspace = _delivery_workspace(tmp_path, adapter, questions)
    manifest = adapter.asset_get("DEMO-FIG-0001", "figure-1")
    representation = next(
        item for item in manifest.asset.representations if item.representation_id == "render-png"
    )
    source = root / Path(manifest.manifest_path).parent / str(representation.path)
    source.write_bytes(b"changed")
    selection = load_yaml_for_test(workspace / "selection.yaml")
    selection["repository_revision"] = adapter.revision()
    (workspace / "selection.yaml").write_text(dump_yaml(selection) + "\n", encoding="utf-8")

    module = _deliver_module()
    with pytest.raises(module.DeliveryError, match="asset hash changed"):
        module.build(workspace, root, compile_pdf=False)


def load_yaml_for_test(path: Path) -> dict[str, Any]:
    value = load_yaml(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.mark.skipif(
    shutil.which("latexmk") is None or shutil.which("xelatex") is None,
    reason="MiKTeX is not available",
)
@pytest.mark.parametrize(
    ("variant", "answer_visible", "solution_visible"),
    [
        ("student", False, False),
        ("answer", True, False),
        ("solution", True, True),
    ],
)
def test_delivery_template_compiles_each_edition(
    project: tuple[Path, Any],
    tmp_path: Path,
    variant: str,
    answer_visible: bool,
    solution_visible: bool,
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    questions = _import_example(adapter)
    workspace = _delivery_workspace(tmp_path, adapter, questions, variant=variant)

    result = _deliver_module().build(workspace, root)

    pdf = workspace / "output" / variant / f"{workspace.name}-{variant}.pdf"
    assert result["pdf_sha256"]
    assert pdf.read_bytes().startswith(b"%PDF")
    assert pdf.stat().st_size > 1_000
    if shutil.which("pdftotext") is not None:
        text_path = tmp_path / f"{variant}.txt"
        extracted = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(pdf), str(text_path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert extracted.returncode == 0, extracted.stderr
        text = text_path.read_text(encoding="utf-8")
        assert ("答案：" in text) is answer_visible
        assert ("解析：" in text) is solution_visible
