"""Regression tests for transactions, dirty indexes, JSONL, and corrupt sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.cli import app
from qbank.diagnostics import doctor, project_status
from qbank.errors import ConflictError, DataValidationError
from qbank.models import Question
from qbank.operations import (
    add_question,
    delete_question,
    ingest_questions,
    query_questions,
)
from qbank.project import initialize_project, load_config
from qbank.search_index import is_dirty, rebuild_index
from qbank.storage import render_question
from qbank.validation import validate_repository


def test_add_rolls_back_source_when_history_write_fails(
    project: tuple[Path, Any],
    question: Question,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    from qbank import transaction

    original = transaction.atomic_write_text

    def fail_history(path: Path, text: str) -> None:
        if path.suffix == ".json":
            raise OSError("history unavailable")
        original(path, text)

    monkeypatch.setattr(transaction, "atomic_write_text", fail_history)
    with pytest.raises(OSError, match="history unavailable"):
        add_question(root, config, question)
    assert not list((root / "questions").rglob(f"{question.id}.md"))
    assert not list((root / ".qbank/history").glob("*.json"))


def test_batch_runtime_failure_rolls_back_every_source(
    project: tuple[Path, Any],
    make_question: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    from qbank import transaction

    original = transaction.atomic_write_text
    calls = 0

    def fail_second_source(path: Path, text: str) -> None:
        nonlocal calls
        if path.suffix == ".md":
            calls += 1
            if calls == 2:
                raise OSError("second source failed")
        original(path, text)

    monkeypatch.setattr(transaction, "atomic_write_text", fail_second_source)
    with pytest.raises(OSError, match="second source"):
        ingest_questions(
            root,
            config,
            [
                make_question(id="OPT-A-0001"),
                make_question(id="OPT-A-0002"),
            ],
        )
    assert not list((root / "questions").rglob("OPT-A-*.md"))
    assert not list((root / ".qbank/history").glob("*.json"))


def test_subject_move_rolls_back_to_original_file(
    project: tuple[Path, Any],
    question: Question,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    add_question(root, config, question)
    original_path = root / "questions/optics/OPT-INT-0001.md"
    before = original_path.read_bytes()
    moved = Question.model_validate(
        {**question.model_dump(), "subject": "mathematics", "title": "Moved"}
    )

    def fail_commit(path: Path, text: str) -> None:
        raise OSError("commit failed")

    monkeypatch.setattr("qbank.transaction.atomic_write_text", fail_commit)
    with pytest.raises(OSError, match="commit failed"):
        add_question(root, config, moved, upsert=True)
    assert original_path.read_bytes() == before
    assert not (root / "questions/mathematics/OPT-INT-0001.md").exists()


def test_index_failure_is_nonfatal_and_marks_dirty(
    project: tuple[Path, Any],
    question: Question,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project

    def fail_index(*args: Any, **kwargs: Any) -> None:
        raise OSError("index unavailable")

    monkeypatch.setattr("qbank.search_index.SQLiteSearchIndex.apply", fail_index)
    result = add_question(root, config, question)
    assert result["ok"]
    assert not result["index_updated"]
    assert result["warnings"][-1]["code"] == "index_dirty"
    assert is_dirty(root, config)
    assert project_status(root, config)["index_dirty"] is True
    check = next(item for item in doctor(root, config)["checks"] if item["name"] == "index_dirty")
    assert check["status"] == "WARN"
    assert rebuild_index(root, config) == 1
    assert not is_dirty(root, config)


def test_jsonl_default_syntax_or_model_error_is_zero_write(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    source = cli_project / "mixed.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps(question_data, ensure_ascii=False),
                '{"id": broken}',
                json.dumps({**question_data, "id": "OPT-A-0002", "difficulty": 9}),
            ]
        ),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["ingest", "mixed.jsonl", "--format", "json"])
    report = json.loads(result.stdout)
    assert result.exit_code == 3
    assert report["written"] == 0
    assert [item["line"] for item in report["results"]] == [1, 2, 3]
    assert report["results"][1]["skipped"] is True
    assert report["results"][2]["errors"][0]["code"] == "model_validation"
    assert not list((cli_project / "questions").rglob("OPT-*.md"))


def test_jsonl_continue_on_error_writes_only_valid_lines(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    source = cli_project / "mixed.jsonl"
    source.write_text(
        json.dumps(question_data, ensure_ascii=False) + "\n" + '{"id": broken}\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "ingest",
            "mixed.jsonl",
            "--continue-on-error",
            "--format",
            "json",
        ],
    )
    report = json.loads(result.stdout)
    assert result.exit_code == 0
    assert report["written"] == 1
    assert report["results"][0]["line"] == 1
    assert report["results"][1]["skipped"] is True
    assert (cli_project / "questions/optics/OPT-INT-0001.md").exists()


def test_deterministic_batch_hash_is_order_independent(
    tmp_path: Path,
    make_question: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixed = "2026-07-19T00:00:00Z"
    monkeypatch.setattr("qbank.storage.utc_now", lambda: fixed)
    monkeypatch.setattr("qbank.history.utc_now", lambda: fixed)
    hashes: list[str] = []
    questions = [
        make_question(id="OPT-A-0001"),
        make_question(id="OPT-A-0002"),
    ]
    for index, batch in enumerate((questions, list(reversed(questions)))):
        root = initialize_project(tmp_path / f"bank-{index}")
        config = load_config(root)
        ingest_questions(root, config, batch)
        record = json.loads(
            next((root / ".qbank/history").glob("*.json")).read_text(encoding="utf-8")
        )
        hashes.append(record["after_hash"])
    assert hashes[0] == hashes[1]


def test_malformed_matching_source_blocks_upsert_and_validates_by_filename(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text("---\nid: OPT-INT-0001\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(DataValidationError):
        add_question(root, config, question, upsert=True)
    assert path.read_bytes() == before
    report = validate_repository(root, config, question_id=question.id)
    assert report.summary.questions == 1
    assert {issue.code for issue in report.issues} == {"invalid_source_file"}


def test_explicit_delete_can_remove_a_malformed_target(
    project: tuple[Path, Any],
) -> None:
    root, config = project
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text("---\nid: OPT-INT-0001\n", encoding="utf-8")
    result = delete_question(root, config, "OPT-INT-0001")
    assert result["ok"]
    assert not path.exists()
    assert len(list((root / ".qbank/history").glob("*.json"))) == 1


def test_query_and_rebuild_refuse_unrelated_malformed_source(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    add_question(root, config, question)
    (root / "questions/optics/BROKEN.md").write_text("not frontmatter", encoding="utf-8")
    with pytest.raises(DataValidationError):
        query_questions(root, config)
    with pytest.raises(DataValidationError):
        rebuild_index(root, config)


def test_duplicate_sources_are_not_silently_queried(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    text = render_question(question)
    (root / "questions/optics/OPT-INT-0001.md").write_text(text, encoding="utf-8")
    (root / "questions/optics/COPY.md").write_text(text, encoding="utf-8")
    with pytest.raises(ConflictError):
        query_questions(root, config)
