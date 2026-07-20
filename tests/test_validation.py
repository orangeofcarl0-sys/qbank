"""Repository and semantic validation tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qbank.models import Question
from qbank.operations import add_question
from qbank.storage import render_question
from qbank.validation import validate_repository


def _codes(report: Any) -> set[str]:
    return {issue.code for issue in report.issues}


def test_valid_question_passes(project: tuple[Path, Any], question: Question) -> None:
    root, config = project
    add_question(root, config, question)
    report = validate_repository(root, config)
    assert report.ok
    assert report.summary.questions == 1


def test_reviewed_without_answer_is_detected(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    invalid = make_question(status="reviewed", answer_md="")
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    report = validate_repository(root, config)
    assert "missing_reviewed_answer" in _codes(report)


def test_missing_asset_is_detected(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    invalid = make_question(assets=["assets/images/missing.svg"])
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    assert "asset_missing" in _codes(validate_repository(root, config))


def test_asset_path_escape_is_rejected(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    invalid = make_question(assets=["../secret.txt"])
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    assert "asset_path_escape" in _codes(validate_repository(root, config))


def test_asset_inside_project_but_outside_assets_is_rejected(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    (root / "other.txt").write_text("x", encoding="utf-8")
    invalid = make_question(assets=["other.txt"])
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    assert "asset_outside_assets" in _codes(validate_repository(root, config))


def test_filename_must_equal_id(project: tuple[Path, Any], question: Question) -> None:
    root, config = project
    path = root / "questions/optics/WRONG.md"
    path.write_text(render_question(question), encoding="utf-8")
    assert "filename_id_mismatch" in _codes(validate_repository(root, config))


def test_empty_stem_is_detected(project: tuple[Path, Any], make_question: Any) -> None:
    with pytest.raises(ValidationError, match="stem_md must not be empty"):
        make_question(stem_md="")


def test_choice_requires_options(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    invalid = make_question(type="single_choice", options_md="", answer_md="A")
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    assert "missing_options" in _codes(validate_repository(root, config))


def test_single_choice_answer_mismatch_warns(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    invalid = make_question(
        type="single_choice",
        options_md="- A. one\n- B. two",
        answer_md="C",
    )
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    report = validate_repository(root, config)
    assert "single_choice_answer_mismatch" in _codes(report)
    assert report.ok


def test_duplicate_fixed_section_is_detected(project: tuple[Path, Any], question: Question) -> None:
    root, config = project
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(question) + "\n## 答案\n\nagain\n", encoding="utf-8")
    assert "duplicate_section" in _codes(validate_repository(root, config))


def test_long_content_in_yaml_is_detected(project: tuple[Path, Any], question: Question) -> None:
    root, config = project
    text = render_question(question).replace(
        "assets: []", 'assets: []\nsolution_md: "must not be here"'
    )
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(text, encoding="utf-8")
    assert "content_in_yaml" in _codes(validate_repository(root, config))


def test_latex_unbalanced_is_warning(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    invalid = make_question(stem_md="unmatched $x")
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    report = validate_repository(root, config)
    assert "latex_dollar_unbalanced" in _codes(report)
    assert report.ok


def test_duplicate_id_across_files_is_detected(
    project: tuple[Path, Any], question: Question
) -> None:
    root, config = project
    for name in ["OPT-INT-0001.md", "COPY.md"]:
        (root / "questions/optics" / name).write_text(render_question(question), encoding="utf-8")
    assert "duplicate_id" in _codes(validate_repository(root, config))


def test_deprecated_empty_answer_is_info(project: tuple[Path, Any], make_question: Any) -> None:
    root, config = project
    deprecated = make_question(status="deprecated", answer_md="")
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(deprecated), encoding="utf-8")
    report = validate_repository(root, config)
    assert report.ok
    assert "deprecated_question" in _codes(report)


def test_invalid_timestamp_has_stable_diagnostic(
    project: tuple[Path, Any], question: Question
) -> None:
    root, config = project
    text = render_question(question).replace(
        "assets: []",
        'assets: []\ncreated_at: "2026-07-19T00:00:00"',
    )
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(text, encoding="utf-8")
    codes = _codes(validate_repository(root, config))
    assert {"invalid_source_file", "invalid_timestamp"} <= codes
