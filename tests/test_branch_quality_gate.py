"""Focused failure-path tests used by the branch-coverage quality gate."""

from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import typer
from pydantic import ValidationError

from qbank.application import load_json_records, parse_json_lines
from qbank.cli_support import abort, read_stdin, resolve_project_path
from qbank.context import ProjectContext
from qbank.domain import InvalidQuestionSource, QuestionRecord, RepositorySnapshot
from qbank.errors import (
    ConflictError,
    DataValidationError,
    MarkdownParseError,
    QuestionNotFoundError,
)
from qbank.models import Question, QuestionPatch
from qbank.project import initialize_project, load_config
from qbank.search_index import SQLiteSearchIndex, _fts_query
from qbank.storage import (
    locate_question,
    parse_question_file,
    parse_question_text,
    parse_sections,
    read_all_questions,
    render_question,
    source_paths_for_id,
    split_frontmatter,
)


def _question_with(question: Question, **updates: Any) -> Question:
    return Question.model_validate({**question.model_dump(), **updates})


def _record(question: Question, path: Path) -> QuestionRecord:
    return QuestionRecord(
        path=path,
        relative_path=path.as_posix(),
        text=render_question(question),
        question=question,
        duplicate_sections=(),
        metadata=question.model_dump(exclude_none=True),
    )


def test_exchange_jsonl_valid_invalid_and_blank_branches(question: Question) -> None:
    encoded = json.dumps(question.model_dump(mode="json", exclude_none=True))
    assert load_json_records(f"\n{encoded}\n", jsonl=True) == [question]
    with pytest.raises(DataValidationError, match="line 1"):
        load_json_records("{not-json}\n", jsonl=True)
    assert parse_json_lines("\n \n") == []


def test_domain_snapshot_identity_conflict_branches(question: Question) -> None:
    requested = question.id
    other = _question_with(question, id="OPT-INT-0002")
    occupied = RepositorySnapshot(
        records=(_record(other, Path(f"{requested}.md")),),
        invalid_sources=(),
        duplicate_ids=frozenset(),
    )
    with pytest.raises(ConflictError, match="occupied"):
        occupied.locate(requested)

    duplicate = _record(question, Path("duplicate.md"))
    duplicates = RepositorySnapshot(
        records=(_record(question, Path("first.md")), duplicate),
        invalid_sources=(),
        duplicate_ids=frozenset({requested}),
    )
    with pytest.raises(ConflictError, match="duplicate"):
        duplicates.locate(requested)

    malformed = InvalidQuestionSource(
        path=Path(f"{requested}.md"),
        relative_path=f"{requested}.md",
        error="broken",
        filename_id=requested,
        frontmatter_id=None,
    )
    mixed = RepositorySnapshot(
        records=(_record(other, Path(f"{other.id}.md")),),
        invalid_sources=(malformed,),
        duplicate_ids=frozenset(),
    )
    assert mixed.source_paths_for_id(requested) == (malformed.path,)


@pytest.mark.parametrize(
    "updates",
    [
        {"title": " "},
        {"assets": [" "]},
        {"created_at": 42},
        {"created_at": "not-a-timestamp"},
    ],
)
def test_question_validator_failure_branches(
    question: Question,
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _question_with(question, **updates)


@pytest.mark.parametrize(
    "payload",
    [
        {"add_topics": [" "]},
        {"add_topics": ["same"], "remove_topics": ["same"]},
    ],
)
def test_patch_topic_failure_branches(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        QuestionPatch.model_validate(payload)


def test_markdown_parser_structural_failure_branches(
    tmp_path: Path,
    question: Question,
) -> None:
    with pytest.raises(MarkdownParseError, match="opening"):
        split_frontmatter("--- trailing\n---\n")
    with pytest.raises(MarkdownParseError, match="closing"):
        split_frontmatter("---\nid: VALUE\n")
    values, duplicates = parse_sections(
        "## Unknown\nignored\n## 题目\nfirst\n## 题目\nsecond\n## 答案\nanswer"
    )
    assert duplicates == ["题目"]
    assert values["stem_md"] == "second"

    with pytest.raises(MarkdownParseError, match="invalid YAML"):
        parse_question_text("---\nvalue: [\n---\n## 题目\nstem")
    with pytest.raises(MarkdownParseError, match="must be a mapping"):
        parse_question_text("---\n- one\n---\n## 题目\nstem")
    with pytest.raises(MarkdownParseError):
        parse_question_text("---\nschema_version: '1.0'\n---\n## 题目\nstem")

    missing = tmp_path / "missing.md"
    with pytest.raises(MarkdownParseError, match="cannot read"):
        parse_question_file(missing)

    timestamped = _question_with(
        question,
        chapter=None,
        created_at="2026-07-19T00:00:00Z",
        updated_at="2026-07-19T00:00:00Z",
    )
    rendered = render_question(timestamped)
    assert "chapter:" not in rendered
    assert "created_at:" in rendered


def _new_bank(path: Path) -> tuple[Path, Any]:
    root = initialize_project(path)
    return root, load_config(root)


def test_legacy_locator_surfaces_invalid_occupied_and_duplicate_sources(
    tmp_path: Path,
    question: Question,
) -> None:
    invalid_root, invalid_config = _new_bank(tmp_path / "invalid")
    invalid_path = invalid_root / f"questions/optics/{question.id}.md"
    invalid_path.write_text("not front matter", encoding="utf-8")
    with pytest.raises(MarkdownParseError, match="invalid source"):
        locate_question(invalid_root, invalid_config, question.id)
    assert source_paths_for_id(invalid_root, invalid_config, question.id) == [invalid_path]
    with pytest.raises(DataValidationError):
        read_all_questions(invalid_root, invalid_config)

    occupied_root, occupied_config = _new_bank(tmp_path / "occupied")
    other = _question_with(question, id="OPT-INT-0002")
    (occupied_root / f"questions/optics/{question.id}.md").write_text(
        render_question(other),
        encoding="utf-8",
    )
    with pytest.raises(ConflictError, match="occupied"):
        locate_question(occupied_root, occupied_config, question.id)
    with pytest.raises(QuestionNotFoundError):
        locate_question(occupied_root, occupied_config, "OPT-MISSING-0001")

    duplicate_root, duplicate_config = _new_bank(tmp_path / "duplicate")
    first = duplicate_root / f"questions/optics/{question.id}.md"
    second = duplicate_root / f"questions/mathematics/{question.id}.md"
    first.write_text(render_question(question), encoding="utf-8")
    second.write_text(render_question(question), encoding="utf-8")
    with pytest.raises(ConflictError, match="duplicate"):
        locate_question(duplicate_root, duplicate_config, question.id)
    with pytest.raises(ConflictError, match="duplicate"):
        read_all_questions(duplicate_root, duplicate_config)


def test_cli_error_stdin_and_path_fallback_branches(
    project: tuple[Path, Any],
    question: Question,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValidationError) as validation:
        _question_with(question, title=" ")
    with pytest.raises(typer.Exit) as validation_exit:
        abort(validation.value, output_format="json")
    assert validation_exit.value.exit_code == 3

    with pytest.raises(typer.Exit) as general_exit:
        abort(RuntimeError("boom"))
    assert general_exit.value.exit_code == 1
    captured = capsys.readouterr()
    assert '"exit_code": 3' in captured.out
    assert "Error: boom" in captured.err

    monkeypatch.setattr(sys, "stdin", io.StringIO("plain"))
    assert read_stdin() == "plain"

    root, config = project
    context = ProjectContext.from_config(root, config)
    missing = Path("does-not-exist.json")
    assert resolve_project_path(context, missing) == (root / missing).resolve()


def test_index_disabled_dirty_empty_and_connection_failure_branches(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    disabled_config = config.model_copy(
        update={"index": config.index.model_copy(update={"enabled": False})}
    )
    disabled = SQLiteSearchIndex(ProjectContext.from_config(root, disabled_config))
    disabled.apply()
    with pytest.raises(DataValidationError, match="index_disabled"):
        disabled.search("text")

    index = SQLiteSearchIndex(ProjectContext.from_config(root, config))
    index.mark_dirty("test")
    with pytest.raises(DataValidationError, match="index_dirty"):
        index.search("text")
    index.clear_dirty()
    with pytest.raises(DataValidationError, match="must not be empty"):
        index.search("  ")

    index.path.unlink()
    with pytest.raises(DataValidationError, match="missing"):
        index.open_existing_writable()
    index.path.write_bytes(b"database")

    def fail_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        del args, kwargs
        raise sqlite3.DatabaseError("connection failed")

    monkeypatch.setattr(sqlite3, "connect", fail_connect)
    with pytest.raises(DataValidationError, match="corrupt"):
        index.open_readonly()
    assert _fts_query(" ") == '""'


def _write_coverage_report(
    path: Path,
    *,
    branch_coverage: bool = True,
    overall_branches: int = 20,
    files: dict[str, dict[str, object]] | None = None,
) -> None:
    if files is None:
        files = {
            "src/qbank/application/service.py": {
                "summary": {"covered_branches": 9, "num_branches": 10}
            },
            "src/qbank/domain/repository.py": {
                "summary": {"covered_branches": 9, "num_branches": 10}
            },
        }
    path.write_text(
        json.dumps(
            {
                "meta": {"branch_coverage": branch_coverage},
                "totals": {
                    "percent_statements_covered": 95.0,
                    "covered_branches": overall_branches,
                    "num_branches": overall_branches,
                },
                "files": files,
            }
        ),
        encoding="utf-8",
    )


def test_branch_gate_rejects_reports_without_branch_measurement(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    _write_coverage_report(report, branch_coverage=False)
    result = _run_coverage_check(report)
    assert result.returncode == 1
    assert "not generated with branch measurement" in result.stderr


def test_branch_gate_rejects_empty_or_missing_layer_branches(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    _write_coverage_report(report, overall_branches=0, files={})
    result = _run_coverage_check(report)
    assert result.returncode == 1
    failures = result.stderr
    assert "no measured branches" in failures
    assert "no files for the application layer" in failures
    assert "no files for the domain layer" in failures


def _run_coverage_check(report: Path) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).parents[1] / "scripts/check_branch_coverage.py"
    return subprocess.run(
        [sys.executable, str(script), str(report)],
        capture_output=True,
        text=True,
        check=False,
    )
