"""Additional end-to-end CLI branch coverage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.cli import app


def test_init_human_output_and_conflict(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    created = runner.invoke(app, ["init", "bank"])
    assert created.exit_code == 0
    assert "Initialized" in created.stdout
    conflict = runner.invoke(app, ["init", "bank"])
    assert conflict.exit_code == 5
    assert "managed file conflict" in conflict.stderr


def test_invalid_output_format_is_rejected_before_any_mutation(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    question_data: dict[str, Any],
) -> None:
    target = tmp_path / "invalid-format-bank"
    initialized = runner.invoke(app, ["init", str(target), "--format", "yaml"])
    assert initialized.exit_code == 3
    assert not target.exists()

    project = tmp_path / "bank"
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", str(project), "--format", "json"]).exit_code == 0
    monkeypatch.chdir(project)
    added = runner.invoke(
        app,
        ["add", "--stdin", "--format", "yaml"],
        input=json.dumps(question_data, ensure_ascii=False),
    )
    assert added.exit_code == 3
    assert not list((project / "questions").rglob("*.md"))


def test_utf8_bom_exchange_files_are_accepted(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    question_file = cli_project / "question-with-bom.json"
    question_file.write_text(
        json.dumps(question_data, ensure_ascii=False),
        encoding="utf-8-sig",
    )
    added = runner.invoke(app, ["add", str(question_file), "--format", "json"])
    assert added.exit_code == 0, added.output

    patch_file = cli_project / "patch-with-bom.json"
    patch_file.write_text('{"set":{"difficulty":4}}', encoding="utf-8-sig")
    patched = runner.invoke(
        app,
        ["patch", question_data["id"], "--file", str(patch_file), "--format", "json"],
    )
    assert patched.exit_code == 0, patched.output
    loaded = runner.invoke(app, ["get", question_data["id"], "--format", "json"])
    assert json.loads(loaded.stdout)["difficulty"] == 4


def test_status_and_doctor_table_and_invalid_formats(runner: CliRunner, cli_project: Path) -> None:
    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0
    assert "Validation errors:" in status.stdout
    invalid_status = runner.invoke(app, ["status", "--format", "yaml"])
    assert invalid_status.exit_code == 3
    doctor = runner.invoke(app, ["doctor"])
    assert doctor.exit_code == 0
    invalid_doctor = runner.invoke(app, ["doctor", "--format", "yaml"])
    assert invalid_doctor.exit_code == 3
    schema = runner.invoke(app, ["schema", "--format", "table"])
    assert schema.exit_code == 3


def test_doctor_cli_returns_nonzero_for_failed_check(runner: CliRunner, cli_project: Path) -> None:
    (cli_project / "schemas/question.schema.json").write_text("{}", encoding="utf-8")
    result = runner.invoke(app, ["doctor", "--format", "json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_add_argument_errors_array_and_dry_run(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    neither = runner.invoke(app, ["add"])
    assert neither.exit_code == 3
    both = runner.invoke(
        app,
        ["add", "missing.json", "--stdin"],
        input=json.dumps(question_data),
    )
    assert both.exit_code == 3
    source = cli_project / "array.json"
    source.write_text(
        json.dumps([question_data, {**question_data, "id": "OPT-A-0002"}]),
        encoding="utf-8",
    )
    array = runner.invoke(app, ["add", str(source), "--format", "json"])
    assert array.exit_code == 3
    dry = runner.invoke(
        app,
        ["add", "--stdin", "--dry-run"],
        input=json.dumps(question_data),
    )
    assert dry.exit_code == 0
    assert "dry-run" in dry.stdout
    assert not list((cli_project / "questions").rglob("OPT-INT-0001.md"))


def test_ingest_human_dry_run_reports_bad_line(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    source = cli_project / "bad.jsonl"
    source.write_text(
        json.dumps(question_data) + "\n" + '{"id": bad}\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["ingest", "bad.jsonl", "--dry-run"])
    assert result.exit_code == 3
    assert "Validated 2; written 0 (dry-run)" in result.stdout
    assert "invalid_json" in result.stderr


def test_validate_table_changed_and_bad_format(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(question_data),
    )
    table = runner.invoke(app, ["validate", "--changed"])
    assert table.exit_code == 0
    assert "1 questions" in table.stdout
    invalid = runner.invoke(app, ["validate", "--format", "yaml"])
    assert invalid.exit_code == 3
    missing = runner.invoke(app, ["validate", "NO-SUCH-0001"])
    assert missing.exit_code == 3
    assert "question_not_found" in missing.stdout


def test_list_get_and_query_output_branches(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    empty = runner.invoke(app, ["list"])
    assert empty.exit_code == 0
    assert "No questions" in empty.stdout
    second = {**question_data, "id": "OPT-A-0002", "title": "Second"}
    for payload in (question_data, second):
        runner.invoke(
            app,
            ["add", "--stdin", "--format", "json"],
            input=json.dumps(payload),
        )
    table = runner.invoke(app, ["list"])
    assert table.exit_code == 0
    assert "title" in table.stdout
    jsonl = runner.invoke(app, ["list", "--format", "jsonl"])
    assert len(jsonl.stdout.strip().splitlines()) == 2
    multi = runner.invoke(
        app,
        ["get", "OPT-INT-0001", "OPT-A-0002", "--format", "json"],
    )
    assert len(json.loads(multi.stdout)) == 2
    get_jsonl = runner.invoke(
        app,
        ["get", "OPT-INT-0001", "OPT-A-0002", "--format", "jsonl"],
    )
    assert len(get_jsonl.stdout.strip().splitlines()) == 2
    assert runner.invoke(app, ["get", "OPT-INT-0001"]).exit_code == 0
    bad_get = runner.invoke(app, ["get", "OPT-INT-0001", "--format", "yaml"])
    assert bad_get.exit_code == 3
    bad_fields = runner.invoke(app, ["query", "--fields", "id,mystery", "--format", "json"])
    assert bad_fields.exit_code == 3
    bad_output = runner.invoke(app, ["query", "--format", "yaml"])
    assert bad_output.exit_code == 3


def test_search_patch_delete_and_index_human_branches(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(question_data),
    )
    search = runner.invoke(app, ["search", "光程"])
    assert search.exit_code == 0
    assert "title" in search.stdout
    empty_search = runner.invoke(app, ["search", "   ", "--format", "json"])
    assert empty_search.exit_code == 3
    patch_file = cli_project / "patch.json"
    patch_file.write_text('{"set":{"difficulty":3}}', encoding="utf-8")
    patched = runner.invoke(
        app,
        [
            "patch",
            "OPT-INT-0001",
            "--file",
            str(patch_file),
            "--format",
            "table",
        ],
    )
    assert patched.exit_code == 0
    assert "1 changes" in patched.stdout
    bad_patch_args = runner.invoke(app, ["patch", "OPT-INT-0001"])
    assert bad_patch_args.exit_code == 3
    dry_delete = runner.invoke(app, ["delete", "OPT-INT-0001", "--dry-run"])
    assert dry_delete.exit_code == 0
    declined = runner.invoke(app, ["delete", "OPT-INT-0001"], input="n\n")
    assert declined.exit_code == 1
    deleted = runner.invoke(
        app,
        ["delete", "OPT-INT-0001", "--yes", "--format", "json"],
    )
    assert deleted.exit_code == 0
    assert json.loads(deleted.stdout)["index_updated"]
    rebuilt = runner.invoke(app, ["index", "rebuild"])
    assert rebuilt.exit_code == 0
    assert "Indexed 0" in rebuilt.stdout


def test_preview_export_and_paper_human_branches(
    runner: CliRunner,
    imported_project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = imported_project
    monkeypatch.chdir(root)
    preview = runner.invoke(app, ["preview"])
    assert preview.exit_code == 0
    assert "Preview:" in preview.stdout
    exported = runner.invoke(app, ["export", "--subject", "optics", "--format", "json"])
    assert exported.exit_code == 0
    report = json.loads(exported.stdout)
    assert report["questions"] == 2
    assert (root / "exports/questions.json").exists()
    bad_export = runner.invoke(app, ["export", "--format", "xml"])
    assert bad_export.exit_code == 6
    validation = runner.invoke(app, ["paper", "validate", "papers/demo-paper.yaml"])
    assert validation.exit_code == 0
    assert "5 questions" in validation.stdout
    built = runner.invoke(
        app,
        [
            "paper",
            "build",
            "papers/demo-paper.yaml",
            "--format",
            "md",
            "--output",
            "build/human.md",
        ],
    )
    assert built.exit_code == 0
    assert "Built md" in built.stdout


def test_paper_validate_failure_human_output(
    runner: CliRunner,
    imported_project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = imported_project
    monkeypatch.chdir(root)
    paper = root / "papers/bad.yaml"
    paper.write_text(
        """
schema_version: "1.0"
title: Bad
sections:
  - title: S
    questions:
      - id: NO-SUCH-0001
        score: 1
""".lstrip(),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["paper", "validate", str(paper)])
    assert result.exit_code == 3
    assert "question does not exist" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["add", "invalid.bin", "--format", "json"],
        ["ingest", "invalid.bin", "--format", "json"],
        ["patch", "OPT-INT-0001", "--file", "invalid.bin", "--format", "json"],
    ],
)
def test_exchange_files_with_invalid_utf8_are_validation_errors(
    runner: CliRunner,
    cli_project: Path,
    arguments: list[str],
) -> None:
    (cli_project / "invalid.bin").write_bytes(b"\xff\xfe\xff")
    result = runner.invoke(app, arguments)
    assert result.exit_code == 3
    assert json.loads(result.stdout)["exit_code"] == 3


@pytest.mark.parametrize(
    "arguments",
    [
        ["query", "--limit", "not-an-integer", "--format", "json"],
        ["get", "--format", "json"],
        ["query", "--unknown-option", "value", "--format=json"],
    ],
)
def test_pre_dispatch_usage_errors_honor_json_format(
    runner: CliRunner,
    cli_project: Path,
    arguments: list[str],
) -> None:
    result = runner.invoke(app, arguments)
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["code"] == "cli_usage"
    assert payload["exit_code"] == 2
    assert result.stderr == ""
