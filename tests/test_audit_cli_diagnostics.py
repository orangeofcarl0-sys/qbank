"""Regression tests for filters, status/doctor, search, and paired CLI flags."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.cli import app
from qbank.diagnostics import _filesystem_semantics_check, doctor, project_status
from qbank.operations import add_question
from qbank.papers import pandoc_command
from qbank.search_index import search
from qbank.storage import render_question


def test_two_character_chinese_search_uses_like_fallback(
    project: tuple[Path, Any], question: Any
) -> None:
    root, config = project
    add_question(root, config, question)
    assert search(root, config, "光程")[0]["id"] == question.id


@pytest.mark.parametrize(
    "arguments",
    [
        ["--type", "mystery"],
        ["--status", "mystery"],
        ["--topic-mode", "xor"],
        ["--difficulty-min", "4", "--difficulty-max", "2"],
    ],
)
def test_invalid_query_filters_return_validation_exit(
    runner: CliRunner,
    cli_project: Path,
    arguments: list[str],
) -> None:
    result = runner.invoke(app, ["query", *arguments, "--format", "json"])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["exit_code"] == 3


def test_status_counts_invalid_files_not_error_diagnostics(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, config = project
    invalid = make_question(
        type="single_choice",
        options_md="",
        answer_md="",
        stem_md="unbalanced $x",
    )
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(invalid), encoding="utf-8")
    status = project_status(root, config)
    assert status["invalid"] == 1
    assert status["validation_errors"] == 2


def test_status_does_not_require_git_executable(
    project: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, config = project

    def missing_git(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("git")

    monkeypatch.setattr("subprocess.run", missing_git)
    assert project_status(root, config)["git_repository"] is False


def test_doctor_reports_schema_drift(project: tuple[Path, Any]) -> None:
    root, config = project
    (root / "schemas/question.schema.json").write_text("{}", encoding="utf-8")
    report = doctor(root, config)
    check = next(item for item in report["checks"] if item["name"] == "schema_question.schema.json")
    assert check["status"] == "FAIL"
    assert not report["ok"]


def test_doctor_reports_stale_index(project: tuple[Path, Any], question: Any) -> None:
    root, config = project
    path = root / "questions/optics/OPT-INT-0001.md"
    path.write_text(render_question(question), encoding="utf-8")
    check = next(item for item in doctor(root, config)["checks"] if item["name"] == "index_stale")
    assert check["status"] == "WARN"


def test_pandoc_command_uses_shell_compatible_parsing(project: tuple[Path, Any]) -> None:
    _, config = project
    changed = config.model_copy(deep=True)
    changed.export.pandoc_command = '"C:\\Program Files\\Pandoc\\pandoc.exe" --sandbox'
    parsed = pandoc_command(changed)
    assert parsed[0].endswith("pandoc.exe")
    assert parsed[1] == "--sandbox"


def test_paper_negative_flags_override_true_yaml_options(
    runner: CliRunner,
    imported_project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = imported_project
    monkeypatch.chdir(root)
    paper = root / "papers/demo-paper.yaml"
    text = paper.read_text(encoding="utf-8")
    text = text.replace("show_question_ids: false", "show_question_ids: true")
    text = text.replace("include_answers: false", "include_answers: true")
    text = text.replace("include_solutions: false", "include_solutions: true")
    text = text.replace("include_rubric: false", "include_rubric: true")
    paper.write_text(text, encoding="utf-8")
    output = root / "build/negative-flags.md"
    result = runner.invoke(
        app,
        [
            "paper",
            "build",
            "papers/demo-paper.yaml",
            "--format",
            "md",
            "--output",
            str(output),
            "--without-answers",
            "--without-solutions",
            "--without-rubric",
            "--hide-ids",
            "--result-format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    rendered = output.read_text(encoding="utf-8")
    assert "#### 答案" not in rendered
    assert "#### 解析" not in rendered
    assert "#### 评分要点" not in rendered
    assert "`OPT-INT-0001`" not in rendered


def test_status_and_doctor_cli_machine_outputs(runner: CliRunner, cli_project: Path) -> None:
    status = runner.invoke(app, ["status", "--format", "json"])
    assert status.exit_code == 0
    assert json.loads(status.stdout)["index_dirty"] is False
    report = runner.invoke(app, ["doctor", "--format", "json"])
    assert report.exit_code == 0
    assert json.loads(report.stdout)["ok"]


def test_external_asset_warning_stays_out_of_json_stderr(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    payload = {
        **question_data,
        "stem_md": "![external](https://example.com/image.png)",
    }
    result = runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(payload, ensure_ascii=False),
    )
    parsed = json.loads(result.stdout)
    assert result.exit_code == 0
    assert parsed["warnings"][0]["code"] == "external_asset"
    assert result.stderr == ""


def test_human_mutation_warning_is_written_to_stderr(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    payload = {
        **question_data,
        "stem_md": "![external](https://example.com/image.png)",
    }
    result = runner.invoke(
        app,
        ["add", "--stdin"],
        input=json.dumps(payload, ensure_ascii=False),
    )
    assert result.exit_code == 0
    assert "external_asset" in result.stderr


def test_doctor_warns_for_synchronized_repository(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = project
    monkeypatch.setenv("OneDrive", str(root.parent))
    check = _filesystem_semantics_check(root)
    assert check.status == "WARN"
    assert "does not guarantee multi-machine" in check.message
