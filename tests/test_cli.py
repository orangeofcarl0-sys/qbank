"""CLI integration and machine-output tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.cli import app
from qbank.models import Question
from qbank.storage import render_question


def test_top_level_help_lists_all_commands(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [
        "init",
        "status",
        "doctor",
        "schema",
        "add",
        "ingest",
        "validate",
        "list",
        "get",
        "query",
        "search",
        "patch",
        "delete",
        "index",
        "preview",
        "export",
        "paper",
        "codex",
    ]:
        assert command in result.stdout


def test_desktop_import_failure_uses_dependency_exit_code(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qbank.desktop

    def fail_launch(_project: Path | None = None) -> int:
        raise ImportError("DLL load failed while importing QtWidgets")

    monkeypatch.setattr(qbank.desktop, "launch", fail_launch)
    result = runner.invoke(app, ["desktop"])
    assert result.exit_code == 7
    assert "PySide6 could not be loaded" in result.stderr


@pytest.mark.parametrize(
    "arguments",
    [
        ["init", "--help"],
        ["doctor", "--help"],
        ["add", "--help"],
        ["ingest", "--help"],
        ["query", "--help"],
        ["index", "rebuild", "--help"],
        ["paper", "validate", "--help"],
        ["paper", "build", "--help"],
        ["codex", "check", "--help"],
        ["codex", "instructions", "--help"],
        ["codex", "install-skill", "--help"],
    ],
)
def test_command_help_is_available(runner: CliRunner, arguments: list[str]) -> None:
    assert runner.invoke(app, arguments).exit_code == 0


def test_init_named_directory_json(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "demo-bank", "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"]
    assert (tmp_path / "demo-bank/qbank.yaml").is_file()


def test_schema_stdout_is_directly_parseable(runner: CliRunner, cli_project: Path) -> None:
    result = runner.invoke(app, ["schema", "--format", "json"])
    assert result.exit_code == 0
    assert "properties" in json.loads(result.stdout)


def test_add_and_get_json_roundtrip(
    runner: CliRunner, cli_project: Path, question_data: dict[str, Any]
) -> None:
    add_result = runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(question_data, ensure_ascii=False),
    )
    assert add_result.exit_code == 0, add_result.output
    assert json.loads(add_result.stdout)["id"] == question_data["id"]
    get_result = runner.invoke(app, ["get", question_data["id"], "--format", "json"])
    assert get_result.exit_code == 0
    loaded = json.loads(get_result.stdout)
    assert loaded["stem_md"] == question_data["stem_md"]


def test_duplicate_add_returns_conflict_exit_code(
    runner: CliRunner, cli_project: Path, question_data: dict[str, Any]
) -> None:
    payload = json.dumps(question_data, ensure_ascii=False)
    assert runner.invoke(app, ["add", "--stdin", "--format", "json"], input=payload).exit_code == 0
    duplicate = runner.invoke(app, ["add", "--stdin", "--format", "json"], input=payload)
    assert duplicate.exit_code == 5
    result = json.loads(duplicate.stdout)
    assert result["ok"] is False
    assert result["code"] == "conflict"


def test_invalid_filter_has_stable_machine_code(
    runner: CliRunner,
    cli_project: Path,
) -> None:
    result = runner.invoke(
        app,
        ["query", "--topic-mode", "neither", "--format", "json"],
    )
    payload = json.loads(result.stdout)
    assert result.exit_code == 3
    assert payload["code"] == "invalid_filter"
    assert "errors.pydantic.dev" not in payload["error"]


@pytest.mark.parametrize(
    ("state", "code"),
    [
        ("missing", "index_unavailable"),
        ("corrupt", "index_unavailable"),
        ("dirty", "index_dirty"),
        ("stale", "index_stale"),
    ],
)
def test_unsearchable_index_has_stable_machine_code(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
    state: str,
    code: str,
) -> None:
    payload = json.dumps(question_data, ensure_ascii=False)
    assert runner.invoke(app, ["add", "--stdin", "--format", "json"], input=payload).exit_code == 0
    index = cli_project / ".qbank/index.sqlite"
    if state == "missing":
        index.unlink()
    elif state == "corrupt":
        index.write_bytes(b"not sqlite")
    elif state == "dirty":
        (cli_project / ".qbank/index.dirty").write_text("dirty", encoding="utf-8")
    else:
        changed = Question.model_validate({**question_data, "title": "Externally changed"})
        source = cli_project / "questions/optics/OPT-INT-0001.md"
        source.write_text(render_question(changed), encoding="utf-8")

    result = runner.invoke(app, ["search", "Michelson", "--format", "json"])
    error = json.loads(result.stdout)
    assert result.exit_code == 3
    assert error["code"] == code


def test_export_output_conflict_has_export_exit_and_code(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    payload = json.dumps(question_data, ensure_ascii=False)
    assert runner.invoke(app, ["add", "--stdin", "--format", "json"], input=payload).exit_code == 0
    conflict = cli_project / "exports/conflict.html"
    conflict.mkdir(parents=True)

    result = runner.invoke(
        app,
        ["export", "--format", "html", "--output", str(conflict)],
    )
    error = json.loads(result.stdout)
    assert result.exit_code == 6
    assert error["code"] == "export_failed"


def test_invalid_command_data_returns_nonzero(
    runner: CliRunner, cli_project: Path, question_data: dict[str, Any]
) -> None:
    invalid = {**question_data, "difficulty": 9}
    result = runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(invalid, ensure_ascii=False),
    )
    assert result.exit_code == 3
    assert json.loads(result.stdout)["exit_code"] == 3


def test_invalid_jsonl_does_not_partially_import(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    source = cli_project / "bad.jsonl"
    source.write_text(
        json.dumps(question_data, ensure_ascii=False) + "\n" + '{"id": broken}\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["ingest", "bad.jsonl", "--format", "json"])
    assert result.exit_code == 3
    assert not list((cli_project / "questions").rglob("OPT-INT-0001.md"))


def test_validate_json_stdout_is_parseable(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(question_data, ensure_ascii=False),
    )
    result = runner.invoke(app, ["validate", "--format", "json"])
    data = json.loads(result.stdout)
    assert result.exit_code == 0
    assert data["summary"]["questions"] == 1


def test_query_and_search_json(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(question_data, ensure_ascii=False),
    )
    query = runner.invoke(app, ["query", "--subject", "optics", "--format", "json"])
    assert json.loads(query.stdout)[0]["id"] == "OPT-INT-0001"
    search = runner.invoke(app, ["search", "光程差", "--format", "json"])
    assert json.loads(search.stdout)[0]["id"] == "OPT-INT-0001"


def test_patch_cli_dry_run_keeps_source(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    runner.invoke(
        app,
        ["add", "--stdin", "--format", "json"],
        input=json.dumps(question_data, ensure_ascii=False),
    )
    path = cli_project / "questions/optics/OPT-INT-0001.md"
    before = path.read_bytes()
    result = runner.invoke(
        app,
        ["patch", "OPT-INT-0001", "--stdin", "--dry-run"],
        input='{"set":{"difficulty":3}}',
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["changes"][0]["field"] == "difficulty"
    assert path.read_bytes() == before


def test_windows_style_input_path(
    runner: CliRunner,
    cli_project: Path,
    question_data: dict[str, Any],
) -> None:
    source = cli_project / "input.json"
    source.write_text(json.dumps(question_data, ensure_ascii=False), encoding="utf-8")
    result = runner.invoke(app, ["add", r".\input.json", "--format", "json"])
    assert result.exit_code == 0, result.output


def test_doctor_json_reports_pandoc_or_warning(runner: CliRunner, cli_project: Path) -> None:
    result = runner.invoke(app, ["doctor", "--format", "json"])
    report = json.loads(result.stdout)
    assert result.exit_code == 0
    assert any(check["name"] == "pandoc" for check in report["checks"])


def test_cli_paper_validate_and_build(
    runner: CliRunner,
    imported_project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = imported_project
    monkeypatch.chdir(root)
    validation = runner.invoke(
        app, ["paper", "validate", r"papers\demo-paper.yaml", "--format", "json"]
    )
    assert validation.exit_code == 0, validation.output
    assert json.loads(validation.stdout)["ok"]
    build = runner.invoke(
        app,
        [
            "paper",
            "build",
            r"papers\demo-paper.yaml",
            "--format",
            "md",
            "--output",
            r"build\cli-paper.md",
            "--result-format",
            "json",
        ],
    )
    assert build.exit_code == 0, build.output
    assert (root / "build/cli-paper.md").is_file()


def test_cli_preview_and_index_rebuild(
    runner: CliRunner,
    imported_project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = imported_project
    monkeypatch.chdir(root)
    rebuilt = runner.invoke(app, ["index", "rebuild", "--format", "json"])
    assert json.loads(rebuilt.stdout)["indexed"] == 5
    preview = runner.invoke(app, ["preview", "--format", "json"])
    assert json.loads(preview.stdout)["questions"] == 5
    assert (root / "build/preview/index.html").is_file()
