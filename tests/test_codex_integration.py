"""Codex repository instructions, Skill discovery, and safe installation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.cli import app
from qbank.context import ProjectContext
from qbank.errors import ConflictError, DataValidationError
from qbank.models import SkillInstallResult
from qbank.services.codex import (
    check_codex_integration,
    codex_instructions,
    install_repository_skill,
    instructions_markdown,
)
from qbank.yaml_io import load_yaml


def test_repository_contains_required_codex_artifacts() -> None:
    root = Path(__file__).parents[1]
    required = [
        "AGENTS.md",
        ".agents/skills/qbank/SKILL.md",
        ".agents/skills/qbank/references/workflows.md",
        ".agents/skills/qbank/references/command-reference.md",
        ".agents/skills/qbank/references/examples.md",
        ".agents/skills/qbank/agents/openai.yaml",
        "tests/codex/discovery-prompts.md",
        "tests/codex/expected-workflows.md",
        "tests/codex/manual-test-checklist.md",
    ]
    assert all((root / path).is_file() for path in required)


def test_skill_frontmatter_and_openai_metadata_are_discoverable() -> None:
    root = Path(__file__).parents[1] / ".agents/skills/qbank"
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    _, yaml_text, _ = skill.split("---", maxsplit=2)
    metadata = load_yaml(yaml_text)
    assert isinstance(metadata, dict)
    assert metadata["name"] == "qbank"
    assert "PDF" in metadata["description"]
    interface = load_yaml((root / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert isinstance(interface, dict)
    assert "$qbank" in interface["interface"]["default_prompt"]


def test_codex_check_warns_not_fails_when_codex_cli_is_absent(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    monkeypatch.chdir(root)
    monkeypatch.setattr("qbank.services.codex.shutil.which", lambda _name: None)
    result = check_codex_integration(
        ProjectContext.from_config(root, config),
        command_probe=lambda _parts: True,
    )
    codex_check = next(check for check in result.checks if check.name == "codex_cli")
    assert result.ok
    assert result.summary.warn == 1
    assert codex_check.status == "WARN"


def test_codex_check_warns_when_path_entry_cannot_execute(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    monkeypatch.chdir(root)
    monkeypatch.setattr("qbank.services.codex.shutil.which", lambda _name: "codex.exe")

    def denied(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError("access denied")

    monkeypatch.setattr("qbank.services.codex.subprocess.run", denied)
    result = check_codex_integration(
        ProjectContext.from_config(root, config),
        command_probe=lambda _parts: True,
    )
    codex_check = next(check for check in result.checks if check.name == "codex_cli")
    assert result.ok
    assert codex_check.status == "WARN"
    assert "cannot be executed" in codex_check.message


def test_codex_check_reports_missing_workflow_command(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    monkeypatch.chdir(root)
    result = check_codex_integration(
        ProjectContext.from_config(root, config),
        command_probe=lambda parts: parts != ("patch",),
    )
    workflow = next(check for check in result.checks if check.name == "workflow_commands")
    assert not result.ok
    assert workflow.status == "FAIL"
    assert "patch" in workflow.message


def test_codex_check_rejects_invalid_skill_frontmatter(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    monkeypatch.chdir(root)
    (root / ".agents/skills/qbank/SKILL.md").write_text(
        "---\nname: wrong\n---\n",
        encoding="utf-8",
    )
    result = check_codex_integration(
        ProjectContext.from_config(root, config),
        command_probe=lambda _parts: True,
    )
    frontmatter = next(check for check in result.checks if check.name == "skill_frontmatter")
    assert not result.ok
    assert frontmatter.status == "FAIL"


def test_codex_check_rejects_working_directory_outside_project(
    project: tuple[Path, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    result = check_codex_integration(
        ProjectContext.from_config(root, config),
        command_probe=lambda _parts: True,
    )
    working = next(check for check in result.checks if check.name == "working_directory")
    assert not result.ok
    assert working.status == "FAIL"


def test_codex_instructions_json_and_markdown(project: tuple[Path, Any]) -> None:
    root, config = project
    result = codex_instructions(ProjectContext.from_config(root, config))
    markdown = instructions_markdown(result)
    assert result.paths["temporary_ai"] == "build/ai"
    assert result.paths["generated_papers"] == "papers/generated"
    assert result.command_sequences["import"][1] == "qbank schema --format json"
    assert "Dry-run every write" in markdown
    assert "qbank paper validate" in markdown


def test_skill_install_is_planned_then_atomic_and_conflict_safe(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    home = tmp_path / "home"
    destination = home / ".agents/skills/qbank"

    planned = install_repository_skill(context, dry_run=True, home=home)
    assert planned.action == "plan"
    assert not destination.exists()

    installed = install_repository_skill(context, dry_run=False, home=home)
    assert installed.action == "installed"
    assert (destination / "SKILL.md").is_file()
    assert not list(destination.parent.glob(".qbank-skill-*"))

    repeated = install_repository_skill(context, dry_run=False, home=home)
    assert repeated.action == "already_installed"

    (destination / "SKILL.md").write_text("different", encoding="utf-8")
    with pytest.raises(ConflictError):
        install_repository_skill(context, dry_run=True, home=home)


def test_skill_install_requires_repository_source(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, config = project
    (root / ".agents/skills/qbank/SKILL.md").unlink()
    with pytest.raises(DataValidationError, match="repository Skill is missing"):
        install_repository_skill(
            ProjectContext.from_config(root, config),
            dry_run=True,
            home=tmp_path / "home",
        )


def test_codex_cli_machine_outputs(
    runner: CliRunner,
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qbank.services.codex._command_probe",
        lambda _context: lambda _parts: True,
    )
    check = runner.invoke(app, ["codex", "check", "--format", "json"])
    assert check.exit_code == 0, check.output
    report = json.loads(check.stdout)
    assert report["ok"]
    assert any(item["name"] == "skill_frontmatter" for item in report["checks"])

    instructions = runner.invoke(app, ["codex", "instructions", "--format", "json"])
    assert instructions.exit_code == 0
    parsed = json.loads(instructions.stdout)
    assert parsed["paths"]["temporary_ai"] == "build/ai"

    markdown = runner.invoke(app, ["codex", "instructions", "--format", "markdown"])
    assert markdown.exit_code == 0
    assert "# qbank Codex instructions" in markdown.stdout


def test_install_skill_dry_run_does_not_write_user_directory(
    runner: CliRunner,
    cli_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(
        "qbank.commands.codex.user_skill_destination",
        lambda: home / ".agents/skills/qbank",
    )

    def install(context: ProjectContext, *, dry_run: bool) -> Any:
        return install_repository_skill(context, dry_run=dry_run, home=home)

    monkeypatch.setattr("qbank.commands.codex.install_repository_skill", install)
    result = runner.invoke(app, ["codex", "install-skill", "--user", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry-run" in result.stdout
    assert not home.exists()


def test_install_skill_requires_confirmation(
    runner: CliRunner,
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes = 0

    def install(context: ProjectContext, *, dry_run: bool) -> SkillInstallResult:
        nonlocal writes
        if not dry_run:
            writes += 1
        return SkillInstallResult(
            ok=True,
            dry_run=dry_run,
            action="plan" if dry_run else "installed",
            source=str(context.root / ".agents/skills/qbank"),
            destination=str(context.root / "unused"),
            files=5,
        )

    monkeypatch.setattr("qbank.commands.codex.install_repository_skill", install)
    result = runner.invoke(app, ["codex", "install-skill"], input="n\n")
    assert result.exit_code == 1
    assert "Install this Skill" in result.stdout
    assert writes == 0


def test_codex_cli_human_check_and_error_boundaries(
    runner: CliRunner,
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qbank.services.codex._command_probe",
        lambda _context: lambda _parts: True,
    )
    human = runner.invoke(app, ["codex", "check"])
    assert human.exit_code == 0
    assert "skill_frontmatter" in human.stdout

    invalid_check = runner.invoke(app, ["codex", "check", "--format", "yaml"])
    assert invalid_check.exit_code == 3
    assert "unsupported output format" in invalid_check.stderr

    invalid_instructions = runner.invoke(
        app,
        ["codex", "instructions", "--format", "yaml"],
    )
    assert invalid_instructions.exit_code == 3
    assert "expected markdown or json" in invalid_instructions.stderr


def test_install_skill_yes_executes_confirmed_plan(
    runner: CliRunner,
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def install(context: ProjectContext, *, dry_run: bool) -> SkillInstallResult:
        calls.append(dry_run)
        return SkillInstallResult(
            ok=True,
            dry_run=dry_run,
            action="plan" if dry_run else "installed",
            source=str(context.root / ".agents/skills/qbank"),
            destination=str(context.root / "installed-skill"),
            files=5,
        )

    monkeypatch.setattr("qbank.commands.codex.install_repository_skill", install)
    result = runner.invoke(app, ["codex", "install-skill", "--user", "--yes"])
    assert result.exit_code == 0
    assert "installed:" in result.stdout
    assert calls == [True, False]
