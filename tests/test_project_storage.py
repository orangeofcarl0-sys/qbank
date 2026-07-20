"""Project initialization and Markdown round-trip tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qbank.errors import ConflictError
from qbank.models import Question
from qbank.operations import add_question
from qbank.project import find_project_root, initialize_project
from qbank.storage import (
    locate_question,
    parse_question_text,
    render_question,
)


def test_init_creates_required_directories(tmp_path: Path) -> None:
    root = initialize_project(tmp_path / "bank")
    required = [
        "qbank.yaml",
        "AGENTS.md",
        ".agents/skills/qbank/SKILL.md",
        ".agents/skills/qbank/agents/openai.yaml",
        ".agents/skills/qbank/references/workflows.md",
        ".agents/skills/qbank/references/command-reference.md",
        ".agents/skills/qbank/references/examples.md",
        "questions/optics",
        "questions/mathematics",
        "questions/electronics",
        "questions/uncategorized",
        "assets/images",
        "assets/diagrams",
        "papers",
        "papers/generated",
        "templates/paper.md.j2",
        "templates/paper.html.j2",
        "exports",
        "build",
        "build/ai",
        "schemas/question.schema.json",
        "schemas/paper.schema.json",
        "schemas/patch.schema.json",
        ".qbank/index.sqlite",
        ".qbank/history",
    ]
    assert all((root / item).exists() for item in required)


def test_find_root_walks_up(project: tuple[Path, object]) -> None:
    root, _ = project
    nested = root / "questions" / "optics" / "nested"
    nested.mkdir()
    assert find_project_root(nested) == root


def test_json_serializes_to_canonical_markdown(question: Question) -> None:
    text = render_question(question)
    assert text.startswith("---\n")
    assert "id: OPT-INT-0001" in text
    positions = [
        text.index(f"## {name}")
        for name in ["题目", "选项", "答案", "解析", "评分要点", "审阅备注"]
    ]
    assert positions == sorted(positions)


def test_markdown_deserializes_to_exchange_json(question: Question) -> None:
    parsed, duplicates, _ = parse_question_text(render_question(question))
    assert duplicates == []
    assert parsed.model_dump(mode="json", exclude_none=True) == question.model_dump(
        mode="json", exclude_none=True
    )


def test_round_trip_preserves_core_fields(question: Question) -> None:
    parsed, _, _ = parse_question_text(render_question(question))
    for field in [
        "id",
        "title",
        "type",
        "subject",
        "topics",
        "difficulty",
        "status",
        "source",
        "stem_md",
        "answer_md",
        "solution_md",
    ]:
        assert getattr(parsed, field) == getattr(question, field)


def test_optional_markdown_sections_may_be_missing(question: Question) -> None:
    text = render_question(question)
    text = text[: text.index("## 审阅备注")]
    parsed, _, _ = parse_question_text(text)
    assert parsed.review_notes_md == ""
    assert parsed.stem_md


def test_add_writes_filename_matching_id(project: tuple[Path, object], question: Question) -> None:
    root, config = project
    result = add_question(root, config, question)
    assert result["ok"]
    assert (root / "questions/optics/OPT-INT-0001.md").is_file()


def test_duplicate_id_is_rejected(project: tuple[Path, object], question: Question) -> None:
    root, config = project
    add_question(root, config, question)
    with pytest.raises(ConflictError):
        add_question(root, config, question)


def test_invalid_id_is_rejected(question_data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Question.model_validate({**question_data, "id": "bad id"})


def test_invalid_difficulty_is_rejected(question_data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Question.model_validate({**question_data, "difficulty": 6})


def test_windows_asset_separator_is_normalized(question_data: dict[str, object]) -> None:
    question = Question.model_validate({**question_data, "assets": [r"assets\images\figure.svg"]})
    assert question.assets == ["assets/images/figure.svg"]


def test_upsert_moves_subject_path(project: tuple[Path, object], question: Question) -> None:
    root, config = project
    add_question(root, config, question)
    updated = Question.model_validate(
        {**question.model_dump(), "subject": "mathematics", "title": "Moved"}
    )
    add_question(root, config, updated, upsert=True)
    path, loaded = locate_question(root, config, question.id)
    assert path == root / "questions/mathematics/OPT-INT-0001.md"
    assert loaded.title == "Moved"
    assert not (root / "questions/optics/OPT-INT-0001.md").exists()


def test_schema_command_model_is_json_serializable() -> None:
    encoded = json.dumps(Question.model_json_schema())
    assert '"properties"' in encoded
