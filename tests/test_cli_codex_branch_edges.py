"""Top-level usage detection and Codex authorization edge coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.cli import app
from qbank.cli_usage import _exception_named, _option_value, _requests_json
from qbank.commands.codex import _emit_mcp_change, _print_skill_plan
from qbank.models import McpConfigChange, SkillFileChange, SkillInstallResult


def test_machine_readable_usage_detection_covers_command_specific_formats() -> None:
    assert _option_value(["--format", "json"], "--format") == "json"
    assert _option_value(["--format=json"], "--format") == "json"
    assert _option_value(["--format"], "--format") is None
    assert _option_value([], "--format") is None
    assert _requests_json(["export", "json"])
    assert _requests_json(["paper", "build", "paper.yaml", "--result-format", "json"])
    assert not _requests_json(["paper", "build", "paper.yaml"])
    assert _requests_json(["status", "--format=json"])
    assert not _requests_json([])
    assert _exception_named(ValueError("x"), "ValueError")
    assert not _exception_named(ValueError("x"), "UsageError")


def test_codex_human_status_and_explicit_authorization_errors(
    project: tuple[Path, Any], runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    monkeypatch.chdir(root)
    status = runner.invoke(app, ["codex", "integration-status", "--format", "table"])
    assert status.exit_code == 0
    assert "DEGRADED" in status.output or "READY" in status.output

    checked = runner.invoke(app, ["codex", "mcp-check", "--format", "table"])
    assert checked.exit_code in {0, 1}
    assert "Configuration:" in checked.output

    missing_scope = runner.invoke(app, ["codex", "install-mcp", "--format", "table"])
    assert missing_scope.exit_code == 3
    assert "explicit --project" in missing_scope.output
    json_without_yes = runner.invoke(app, ["codex", "install-mcp", "--project", "--format", "json"])
    assert json_without_yes.exit_code == 3
    assert "explicit --yes" in json_without_yes.output
    conflicting_skill_scope = runner.invoke(
        app,
        ["codex", "install-skill", "--user", "--project", "--dry-run"],
    )
    assert conflicting_skill_scope.exit_code == 3
    assert "choose only one" in conflicting_skill_scope.output


def test_codex_human_change_presenters_include_backups(capsys: pytest.CaptureFixture[str]) -> None:
    _emit_mcp_change(
        McpConfigChange(
            ok=True,
            action="install",
            dry_run=False,
            configuration=".codex/config.toml",
            repository="C:/bank",
            changed=True,
            backup="backup.toml",
        ),
        "table",
    )
    _print_skill_plan(
        SkillInstallResult(
            ok=True,
            dry_run=False,
            action="updated",
            source="package:qbank",
            destination=".agents/skills/qbank",
            files=1,
            scope="project",
            backup=".qbank/backups/skill",
            changes=[SkillFileChange(path="SKILL.md", action="modify")],
        )
    )
    output = capsys.readouterr().out
    assert "Backup:" in output and "modify: SKILL.md" in output
