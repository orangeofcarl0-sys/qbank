"""Batch mutation, patch, history, query, and index tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qbank.context import ProjectContext
from qbank.models import QuestionPatch
from qbank.operations import (
    add_question,
    apply_patch,
    delete_question,
    ingest_questions,
    query_questions,
)
from qbank.search_index import SQLiteSearchIndex, index_path, rebuild_index, search
from qbank.storage import locate_question


def test_jsonl_style_batch_import_succeeds(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    questions = [
        make_question(id="OPT-INT-0001"),
        make_question(id="OPT-INT-0002", title="Second"),
    ]
    result = ingest_questions(root, config, questions)
    assert result["ok"]
    assert result["written"] == 2
    assert locate_question(root, config, "OPT-INT-0002")[1].title == "Second"


def test_batch_error_does_not_partially_write(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    duplicate = make_question()
    result = ingest_questions(root, config, [duplicate, duplicate])
    assert not result["ok"]
    assert result["written"] == 0
    assert not list((root / "questions").rglob("OPT-INT-0001.md"))


def test_continue_on_error_writes_valid_records(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    existing = make_question(id="OPT-INT-0001")
    add_question(root, config, existing)
    valid = make_question(id="OPT-INT-0002")
    result = ingest_questions(root, config, [existing, valid], continue_on_error=True)
    assert result["ok"]
    assert result["written"] == 1
    locate_question(root, config, "OPT-INT-0002")


def test_upsert_updates_existing_question(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    add_question(root, config, make_question())
    updated = make_question(title="Updated title")
    result = ingest_questions(root, config, [updated], upsert=True)
    assert result["written"] == 1
    assert locate_question(root, config, updated.id)[1].title == "Updated title"


def test_patch_dry_run_does_not_write(project: tuple[Path, Any], question: Any) -> None:
    root, config = project
    add_question(root, config, question)
    path, _ = locate_question(root, config, question.id)
    before = path.read_bytes()
    patch = QuestionPatch.model_validate({"set": {"difficulty": 3}})
    result = apply_patch(root, config, question.id, patch, dry_run=True)
    assert result["changes"][0]["field"] == "difficulty"
    assert path.read_bytes() == before


def test_patch_returns_field_level_diff(project: tuple[Path, Any], question: Any) -> None:
    root, config = project
    add_question(root, config, question)
    patch = QuestionPatch.model_validate({"set": {"difficulty": 3}, "add_topics": ["round-trip"]})
    result = apply_patch(root, config, question.id, patch)
    changed = {item["field"] for item in result["changes"]}
    assert {"difficulty", "topics"} <= changed
    loaded = locate_question(root, config, question.id)[1]
    assert loaded.difficulty == 3
    assert "round-trip" in loaded.topics


def test_patch_cannot_modify_id() -> None:
    with pytest.raises(ValidationError):
        QuestionPatch.model_validate({"set": {"id": "OPT-NEW-0001"}})


def test_patch_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        QuestionPatch.model_validate({"set": {"mystery": 1}})


def test_mutations_write_history(project: tuple[Path, Any], question: Any) -> None:
    root, config = project
    add_question(root, config, question)
    apply_patch(
        root,
        config,
        question.id,
        QuestionPatch.model_validate({"set": {"difficulty": 3}}),
    )
    logs = list((root / ".qbank/history").glob("*.json"))
    assert len(logs) == 2
    assert '"operation": "patch"' in logs[-1].read_text(encoding="utf-8")


def test_delete_retains_assets(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    asset = root / "assets/images/kept.svg"
    asset.write_text("<svg/>", encoding="utf-8")
    question = make_question(assets=["assets/images/kept.svg"])
    add_question(root, config, question)
    delete_question(root, config, question.id)
    assert asset.exists()
    assert not list((root / "questions").rglob(f"{question.id}.md"))


def test_query_filters_subject_status_and_difficulty(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    items = [
        make_question(id="OPT-A-0001", difficulty=1, status="draft"),
        make_question(
            id="MATH-A-0001",
            subject="mathematics",
            difficulty=4,
            status="verified",
        ),
        make_question(id="OPT-A-0002", difficulty=3, status="reviewed"),
    ]
    for item in items:
        add_question(root, config, item)
    found = query_questions(
        root,
        config,
        subject="optics",
        status="reviewed",
        difficulty_min=2,
        difficulty_max=3,
    )
    assert [item.id for item in found] == ["OPT-A-0002"]


def test_topic_and_mode(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    add_question(
        root,
        config,
        make_question(id="OPT-A-0001", topics=["alpha", "beta"]),
    )
    add_question(
        root,
        config,
        make_question(id="OPT-A-0002", topics=["alpha"]),
    )
    found = query_questions(root, config, topics=["alpha", "beta"], topic_mode="and")
    assert [item.id for item in found] == ["OPT-A-0001"]


def test_topic_or_mode(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    add_question(
        root,
        config,
        make_question(id="OPT-A-0001", topics=["alpha"]),
    )
    add_question(
        root,
        config,
        make_question(id="OPT-A-0002", topics=["beta"]),
    )
    found = query_questions(root, config, topics=["alpha", "beta"], topic_mode="or")
    assert {item.id for item in found} == {"OPT-A-0001", "OPT-A-0002"}


def test_fts_search_finds_stem(project: tuple[Path, Any], question: Any) -> None:
    root, config = project
    add_question(root, config, question)
    results = search(root, config, "反射镜")
    assert results[0]["id"] == question.id


def test_deleted_index_can_be_rebuilt(project: tuple[Path, Any], question: Any) -> None:
    root, config = project
    add_question(root, config, question)
    index_path(root, config).unlink()
    assert rebuild_index(root, config) == 1
    assert search(root, config, "Michelson")[0]["id"] == question.id


def test_delete_removes_fts_row(project: tuple[Path, Any], question: Any) -> None:
    root, config = project
    add_question(root, config, question)
    delete_question(root, config, question.id)
    assert search(root, config, "Michelson") == []


def test_tag_count_and_cooccurrence_projections_follow_mutations(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    first = make_question(id="OPT-TAGS-0001", topics=["alpha", "beta"])
    second = make_question(id="OPT-TAGS-0002", topics=["alpha", "gamma"])
    ingest_questions(root, config, [first, second])
    index = SQLiteSearchIndex(ProjectContext.from_config(root, config))

    assert index.tag_projection() == (
        {"alpha": 2, "beta": 1, "gamma": 1},
        {("alpha", "beta"): 1, ("alpha", "gamma"): 1},
    )

    apply_patch(
        root,
        config,
        first.id,
        QuestionPatch(remove_topics=["beta"], add_topics=["gamma"]),
    )
    assert index.tag_projection() == (
        {"alpha": 2, "gamma": 2},
        {("alpha", "gamma"): 2},
    )

    delete_question(root, config, second.id)
    assert index.tag_projection() == (
        {"alpha": 1, "gamma": 1},
        {("alpha", "gamma"): 1},
    )
