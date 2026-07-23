"""Batch mutation, patch, history, query, and index tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.models import QueryFilters, QuestionPatch
from qbank.operations import (
    add_question,
    apply_patch,
    delete_question,
    ingest_questions,
    query_questions,
)
from qbank.search_index import (
    SQLiteSearchIndex,
    apply_index_changes,
    clear_dirty,
    connect_index,
    dirty_path,
    index_health,
    index_path,
    is_dirty,
    last_updated,
    mark_dirty,
    read_index_documents,
    rebuild_index,
    remove_question,
    search,
    update_question,
)
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


def test_sqlite_summary_query_covers_all_structured_filters(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    matching = make_question(
        id="OPT-FILTER-0001",
        type="calculation",
        subject="optics",
        chapter="interferometry",
        topics=["alpha", "beta"],
        difficulty=3,
        status="reviewed",
        language="zh-CN",
        created_at="2025-02-03T04:05:06Z",
        stem_md="interference fringe pattern",
    )
    excluded = make_question(
        id="OPT-FILTER-0002",
        topics=["alpha", "gamma"],
        created_at="2024-02-03T04:05:06Z",
        stem_md="interference fringe pattern",
    )
    ingest_questions(root, config, [matching, excluded])
    index = SQLiteSearchIndex(ProjectContext.from_config(root, config))

    exact = index.query(
        QueryFilters(
            subject="optics",
            chapter="interferometry",
            topics=["alpha", "beta"],
            excluded_topics=["gamma"],
            topic_mode="and",
            question_type="calculation",
            status="reviewed",
            difficulty_min=2,
            difficulty_max=4,
            language="zh-CN",
            year=2025,
            text="interference",
            limit=10,
            offset=0,
        )
    )
    assert [item.id for item in exact] == [matching.id]
    assert exact[0].subject == "optics"
    assert exact[0].difficulty == 3

    like = index.query(QueryFilters(topics=["alpha", "missing"], topic_mode="or", text="%"))
    assert like == []
    paged = index.query(QueryFilters(limit=1, offset=1))
    assert [item.id for item in paged] == [excluded.id]


def test_index_compatibility_adapters_and_disabled_paths(
    project: tuple[Path, Any], question: Any
) -> None:
    root, config = project
    add_question(root, config, question)

    assert dirty_path(root, config).name == "index.dirty"
    mark_dirty(root, config, "test")
    assert is_dirty(root, config)
    with pytest.raises(DataValidationError, match="index_dirty"):
        search(root, config, "Michelson")
    clear_dirty(root, config)
    assert not is_dirty(root, config)

    updated = question.model_copy(update={"title": "Projection-only title", "topics": ["new"]})
    update_question(root, config, updated)
    assert read_index_documents(root, config)[question.id][0] == "Projection-only title"
    assert last_updated(root, config) is not None
    with connect_index(root, config) as connection:
        assert connection.execute("SELECT count(*) FROM question_fts").fetchone()[0] == 1

    remove_question(root, config, question.id)
    assert read_index_documents(root, config) == {}
    apply_index_changes(root, config, questions=(question,))
    assert question.id in read_index_documents(root, config)
    apply_index_changes(root, config, deleted_ids=(question.id,))
    assert read_index_documents(root, config) == {}
    assert index_health(root, config).state == "clean"

    disabled = config.model_copy(
        update={"index": config.index.model_copy(update={"enabled": False})}
    )
    disabled_index = SQLiteSearchIndex(ProjectContext.from_config(root, disabled))
    disabled_index.apply(questions=(question,))
    with pytest.raises(DataValidationError, match="index_disabled"):
        disabled_index.search("Michelson")
    with pytest.raises(DataValidationError, match="index_disabled"):
        disabled_index.query(QueryFilters())
    with pytest.raises(DataValidationError, match="index_disabled"):
        disabled_index.ensure_revision("revision")


def test_index_read_paths_reject_missing_corrupt_dirty_and_empty_search(
    project: tuple[Path, Any], question: Any
) -> None:
    root, config = project
    add_question(root, config, question)
    index = SQLiteSearchIndex(ProjectContext.from_config(root, config))

    with pytest.raises(DataValidationError, match="invalid_filter"):
        index.search("  ")
    index.mark_dirty("test")
    with pytest.raises(DataValidationError, match="index_dirty"):
        index.query(QueryFilters())
    index.clear_dirty()

    index.path.unlink()
    with pytest.raises(DataValidationError, match="index_unavailable"):
        index.open_readonly()
    with pytest.raises(DataValidationError, match="search index is missing"):
        index.open_existing_writable()
    assert index.health().state == "missing"

    index.path.write_bytes(b"not a sqlite database")
    with pytest.raises(DataValidationError, match="corrupt or incompatible"):
        index.open_readonly()
    with pytest.raises(sqlite3.DatabaseError, match="file is not a database"):
        index.open_existing_writable()
    assert index.health().state == "corrupt"
