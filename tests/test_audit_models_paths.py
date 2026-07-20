"""Regression tests for strict models, schemas, paths, and initialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from qbank.cli import app
from qbank.errors import ConflictError, DataValidationError
from qbank.models import (
    Paper,
    PathsConfig,
    ProjectConfig,
    QueryFilters,
    Question,
    QuestionPatch,
)
from qbank.project import (
    DEFAULT_CONFIG,
    initialize_project,
    load_config,
    path_for,
)
from qbank.schemas import all_schemas


@pytest.mark.parametrize("missing", ["schema_version", "stem_md"])
def test_question_required_fields_are_really_required(
    question_data: dict[str, Any], missing: str
) -> None:
    data = dict(question_data)
    data.pop(missing)
    with pytest.raises(ValidationError):
        Question.model_validate(data)


@pytest.mark.parametrize("topics", [[], [""], ["  "]])
def test_topics_require_at_least_one_nonempty_value(
    question_data: dict[str, Any], topics: list[str]
) -> None:
    with pytest.raises(ValidationError):
        Question.model_validate({**question_data, "topics": topics})


def test_timestamps_require_timezone_and_normalize_to_z(
    question_data: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Question.model_validate({**question_data, "created_at": "2026-07-18T12:00:00"})
    question = Question.model_validate(
        {
            **question_data,
            "created_at": "2026-07-18T20:00:00+08:00",
            "updated_at": "2026-07-18T12:00:00Z",
        }
    )
    assert question.created_at == "2026-07-18T12:00:00Z"
    assert question.updated_at == "2026-07-18T12:00:00Z"


@pytest.mark.parametrize("value", ["2026/07/18", "20260718", "18-07-2026"])
def test_paper_date_requires_extended_iso(value: str) -> None:
    with pytest.raises(ValidationError):
        Paper.model_validate(
            {
                "schema_version": "1.0",
                "title": "Paper",
                "date": value,
                "sections": [
                    {
                        "title": "S",
                        "questions": [{"id": "OPT-X-0001", "score": 1}],
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "data",
    [
        {"topic_mode": "xor"},
        {"question_type": "mystery"},
        {"status": "unknown"},
        {"limit": 0},
        {"offset": -1},
        {"difficulty_min": 4, "difficulty_max": 2},
    ],
)
def test_query_filter_model_rejects_invalid_input(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        QueryFilters.model_validate(data)


@pytest.mark.parametrize(
    "value",
    [
        "../questions",
        "/tmp/questions",
        r"C:\outside",
        ".",
        "",
    ],
)
def test_configured_paths_must_be_project_relative(value: str) -> None:
    with pytest.raises(ValidationError):
        PathsConfig(questions=value)


def test_configured_directories_must_not_overlap() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        PathsConfig(questions="content", assets="content/assets")


def test_reference_docx_must_stay_inside_project() -> None:
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(
            {
                "schema_version": "1.0",
                "export": {"reference_docx": "../reference.docx"},
            }
        )


def test_path_for_rejects_symlink_escape(
    project: tuple[Path, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    link = root / "escaped"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        original_resolve = Path.resolve

        def simulated_resolve(path: Path, strict: bool = False) -> Path:
            if str(path).casefold() == str(link).casefold():
                return outside.absolute()
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", simulated_resolve)
    escaped = config.model_copy(
        update={"paths": config.paths.model_copy(update={"questions": "escaped"})}
    )
    with pytest.raises(DataValidationError, match="escapes"):
        path_for(root, escaped, "questions")


def test_load_config_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bank"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        link = root / "escaped"
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        original_resolve = Path.resolve

        def simulated_resolve(path: Path, strict: bool = False) -> Path:
            if str(path).casefold() == str(link).casefold():
                return outside.absolute()
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", simulated_resolve)
    (root / "qbank.yaml").write_text(
        DEFAULT_CONFIG.replace("questions: questions", "questions: escaped"),
        encoding="utf-8",
    )
    with pytest.raises(DataValidationError, match="escapes"):
        load_config(root)


def test_init_conflict_is_zero_write_and_force_is_explicit(tmp_path: Path) -> None:
    root = tmp_path / "bank"
    template = root / "templates/paper.md.j2"
    template.parent.mkdir(parents=True)
    template.write_text("keep me", encoding="utf-8")
    with pytest.raises(ConflictError):
        initialize_project(root)
    assert template.read_text(encoding="utf-8") == "keep me"
    assert not (root / "qbank.yaml").exists()
    initialize_project(root, force=True)
    assert template.read_text(encoding="utf-8") != "keep me"


def test_static_schemas_match_models_exactly() -> None:
    for filename, expected in all_schemas().items():
        actual = json.loads(
            (Path(__file__).parents[1] / "schemas" / filename).read_text(encoding="utf-8")
        )
        assert actual == expected


@pytest.mark.parametrize("kind", ["question", "paper", "patch"])
def test_schema_cli_supports_every_kind(runner: CliRunner, cli_project: Path, kind: str) -> None:
    result = runner.invoke(app, ["schema", "--kind", kind, "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == all_schemas()[f"{kind}.schema.json"]


def test_schema_cli_rejects_unknown_kind(runner: CliRunner, cli_project: Path) -> None:
    result = runner.invoke(app, ["schema", "--kind", "mystery", "--format", "json"])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["exit_code"] == 3


def test_patch_schema_and_runtime_reject_unknown_and_wrong_typed_set_values() -> None:
    set_schema = QuestionPatch.model_json_schema()["properties"]["set"]
    assert set_schema["additionalProperties"] is False
    assert "id" not in set_schema["properties"]
    assert set_schema["properties"]["difficulty"]["type"] == "integer"
    with pytest.raises(ValidationError):
        QuestionPatch.model_validate({"set": {"id": "OPT-NEW-0001"}})
    with pytest.raises(ValidationError):
        QuestionPatch.model_validate({"set": {"difficulty": "hard"}})
