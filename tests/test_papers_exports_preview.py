"""Paper validation/build, normal export, and preview tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from qbank.errors import DependencyMissingError, ExportError
from qbank.exporters import export_questions
from qbank.models import Paper
from qbank.operations import add_question, query_questions
from qbank.papers import build_paper, load_paper, validate_paper
from qbank.preview import build_preview


def _demo_paper(root: Path) -> Path:
    return root / "papers/demo-paper.yaml"


def test_demo_paper_validates(imported_project: tuple[Path, Any]) -> None:
    root, config = imported_project
    paper = load_paper(_demo_paper(root))
    report = validate_paper(root, config, paper)
    assert report["ok"]
    assert report["summary"]["questions"] == 5


def test_paper_missing_id_is_rejected(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    paper = Paper.model_validate(
        {
            "schema_version": "1.0",
            "title": "Missing",
            "sections": [
                {
                    "title": "S",
                    "questions": [{"id": "NO-SUCH-0001", "score": 5}],
                }
            ],
        }
    )
    report = validate_paper(root, config, paper)
    assert not report["ok"]
    assert report["issues"][0]["code"] == "missing_question"


def test_paper_duplicate_id_is_detected(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    paper = Paper.model_validate(
        {
            "schema_version": "1.0",
            "title": "Duplicate",
            "sections": [
                {
                    "title": "S",
                    "questions": [
                        {"id": "OPT-INT-0001", "score": 5},
                        {"id": "OPT-INT-0001", "score": 5},
                    ],
                }
            ],
        }
    )
    codes = {item["code"] for item in validate_paper(root, config, paper)["issues"]}
    assert "duplicate_question" in codes


def test_total_score_mismatch_is_detected(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    paper = load_paper(_demo_paper(root))
    wrong = Paper.model_validate(
        {
            **paper.model_dump(),
            "metadata": {**paper.metadata.model_dump(), "total_score": 999},
        }
    )
    codes = {item["code"] for item in validate_paper(root, config, wrong)["issues"]}
    assert "total_score_mismatch" in codes


def test_total_score_is_calculated_when_omitted(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    paper = load_paper(_demo_paper(root))
    automatic = Paper.model_validate(
        {
            **paper.model_dump(),
            "metadata": {**paper.metadata.model_dump(), "total_score": None},
        }
    )
    report = validate_paper(root, config, automatic)
    assert report["ok"]
    assert report["summary"]["total_score"] == 40


def test_markdown_student_paper_omits_answers(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    result = build_paper(root, config, _demo_paper(root), output_format="md")
    text = (root / result["output"]).read_text(encoding="utf-8")
    assert "#### 答案" not in text
    assert "Michelson" in text


def test_markdown_solution_paper_includes_answer_and_solution(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    result = build_paper(
        root,
        config,
        _demo_paper(root),
        output_format="md",
        output=Path("build/solutions.md"),
        with_solutions=True,
    )
    text = (root / result["output"]).read_text(encoding="utf-8")
    assert "#### 答案" in text
    assert "#### 解析" in text
    assert "$3.0" in text


def test_student_paper_does_not_copy_answer_only_assets(
    project: tuple[Path, Any],
    question: Any,
) -> None:
    root, config = project
    question_asset = root / "assets/images/question.png"
    answer_asset = root / "assets/images/answer.png"
    question_asset.write_bytes(b"question")
    answer_asset.write_bytes(b"answer")
    with_assets = question.model_copy(
        update={
            "assets": ["assets/images/question.png", "assets/images/answer.png"],
            "stem_md": "![question](assets/images/question.png)",
            "answer_md": "![answer](assets/images/answer.png)",
        }
    )
    add_question(root, config, with_assets)
    paper = root / "papers/asset-visibility.yaml"
    paper.write_text(
        "\n".join(
            (
                "schema_version: '1.0'",
                "title: Asset visibility",
                "sections:",
                "  - title: Main",
                "    questions:",
                f"      - id: {question.id}",
                "        score: 10",
                "",
            )
        ),
        encoding="utf-8",
    )

    student = build_paper(
        root,
        config,
        paper,
        output_format="md",
        output=Path("exports/student.md"),
        with_answers=False,
        with_solutions=False,
    )
    answer = build_paper(
        root,
        config,
        paper,
        output_format="md",
        output=Path("answers/answer.md"),
        with_answers=True,
    )

    assert student["assets"] == ["assets/images/question.png"]
    assert not (root / "exports/assets/images/answer.png").exists()
    assert answer["assets"] == [
        "assets/images/answer.png",
        "assets/images/question.png",
    ]
    assert (root / "answers/assets/images/answer.png").read_bytes() == b"answer"


def test_html_paper_is_created(imported_project: tuple[Path, Any]) -> None:
    root, config = imported_project
    result = build_paper(root, config, _demo_paper(root), output_format="html")
    text = (root / result["output"]).read_text(encoding="utf-8")
    assert "<!doctype html>" in text
    assert "MathJax" in text
    assert "<h1>光学与理工基础测试</h1>" in text
    assert "&lt;h1&gt;" not in text


def test_pandoc_missing_has_clear_dependency_error(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    broken = config.model_copy(deep=True)
    broken.export.pandoc_command = "definitely-no-such-pandoc-binary"
    with pytest.raises(DependencyMissingError, match="Pandoc"):
        build_paper(root, broken, _demo_paper(root), output_format="docx")


def test_pandoc_missing_does_not_create_output_or_assets(
    imported_project: tuple[Path, Any],
) -> None:
    root, config = imported_project
    broken = config.model_copy(deep=True)
    broken.export.pandoc_command = "definitely-no-such-pandoc-binary"
    output = root / "new-output/paper.docx"

    with pytest.raises(DependencyMissingError):
        build_paper(
            root,
            broken,
            _demo_paper(root),
            output_format="docx",
            output=output,
        )

    assert not output.parent.exists()


def test_real_pandoc_docx_round_trip_when_available(
    imported_project: tuple[Path, Any],
) -> None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        pytest.skip("Pandoc is not installed")
    root, config = imported_project
    result = build_paper(
        root,
        config,
        _demo_paper(root),
        output_format="docx",
        output=Path("build/round-trip.docx"),
    )
    output = root / result["output"]
    completed = subprocess.run(
        [pandoc, str(output), "--to", "plain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0
    assert "qbank" in completed.stdout


def test_preview_generates_index(imported_project: tuple[Path, Any]) -> None:
    root, config = imported_project
    result = build_preview(root, config)
    index = root / result["output"] / "index.html"
    assert index.is_file()
    text = index.read_text(encoding="utf-8")
    assert 'id="search"' in text
    assert 'id="difficulty"' in text
    assert "<details><summary>答案</summary>" in text


@pytest.mark.parametrize("output_format", ["json", "jsonl", "md", "html"])
def test_normal_export_formats(imported_project: tuple[Path, Any], output_format: str) -> None:
    root, config = imported_project
    questions = query_questions(root, config, subject="optics")
    output = root / "exports" / f"optics.{output_format}"
    result = export_questions(
        root,
        config,
        questions,
        output_format=output_format,
        output=output,
    )
    assert result["questions"] == 2
    assert output.is_file()
    if output_format == "json":
        assert len(json.loads(output.read_text(encoding="utf-8"))) == 2
    if output_format == "jsonl":
        assert len(output.read_text(encoding="utf-8").splitlines()) == 2


def test_export_conflict_leaves_no_partial_assets(
    project: tuple[Path, Any],
    question: Any,
) -> None:
    root, config = project
    with_asset = question.model_copy(
        update={
            "assets": ["assets/images/interference.svg"],
            "stem_md": "![diagram](assets/images/interference.svg)",
        }
    )
    output = root / "exports/result.html"
    output.mkdir(parents=True)

    with pytest.raises(ExportError, match="directory"):
        export_questions(
            root,
            config,
            [with_asset],
            output_format="html",
            output=output,
        )

    assert not (root / "exports/assets").exists()
