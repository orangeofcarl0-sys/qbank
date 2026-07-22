"""Codex repository instructions, Skill discovery, and safe installation tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from qbank.cli import app
from qbank.codex_manifest import (
    COMPLETION_HANDOFF_FIELDS,
    CONTEXT_AUTHORIZATION_MODES,
    CONTEXT_REQUIRED_FIELDS,
    DIGITIZE_SKILL_FILES,
    INTEGRATION_REVISION,
    REQUIRED_COMMANDS,
    SKILL_FILES,
    WORKFLOWS,
)
from qbank.context import ProjectContext
from qbank.errors import ConflictError, DataValidationError
from qbank.models import SkillInstallResult
from qbank.services.codex import (
    canonical_skill_contents,
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
        ".agents/skills/qbank/references/context-handoff.md",
        ".agents/skills/qbank/references/workflows.md",
        ".agents/skills/qbank/references/command-reference.md",
        ".agents/skills/qbank/references/examples.md",
        ".agents/skills/qbank/agents/openai.yaml",
        ".agents/skills/qbank-digitize/SKILL.md",
        ".agents/skills/qbank-digitize/agents/openai.yaml",
        ".agents/skills/qbank-digitize/assets/digitization-profile.yaml",
        ".agents/skills/qbank-digitize/assets/classification-map.csv",
        ".agents/skills/qbank-digitize/references/intake.md",
        ".agents/skills/qbank-digitize/references/field-policy.md",
        ".agents/skills/qbank-digitize/references/calibration.md",
        "tests/codex/discovery-prompts.md",
        "tests/codex/expected-workflows.md",
        "tests/codex/manual-test-checklist.md",
        "tests/codex/digitization-prompts.md",
        "tests/codex/digitization-expected.md",
        "tests/codex/digitization-manual-checklist.md",
    ]
    assert all((root / path).is_file() for path in required)


def test_manifest_workflows_are_covered_by_packaged_guidance() -> None:
    root = Path(__file__).parents[1] / "src/qbank/resources/init/codex/skill"
    guidance = "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in (
            "SKILL.md",
            "references/context-handoff.md",
            "references/workflows.md",
            "references/command-reference.md",
        )
    )
    for workflow in WORKFLOWS:
        for step in workflow.steps:
            if step.command_path:
                assert " ".join(step.command_path) in guidance
    assert "explicit user request" in guidance
    assert "blocking interactive commands" in guidance
    assert "source project as read-only" in guidance
    assert "do not infer the target" in guidance.lower()


def test_repository_skill_matches_packaged_canonical_tree() -> None:
    root = Path(__file__).parents[1]
    repository_skill = root / ".agents/skills/qbank"
    packaged_skill = root / "src/qbank/resources/init/codex/skill"
    for relative in SKILL_FILES:
        assert (repository_skill / relative).read_bytes() == (
            packaged_skill / relative
        ).read_bytes()

    repository_digitize = root / ".agents/skills/qbank-digitize"
    packaged_digitize = root / "src/qbank/resources/init/codex/qbank-digitize"
    for relative in DIGITIZE_SKILL_FILES:
        assert (repository_digitize / relative).read_bytes() == (
            packaged_digitize / relative
        ).read_bytes()


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


def test_digitize_skill_is_domain_specific_and_composes_with_qbank() -> None:
    root = Path(__file__).parents[1] / ".agents/skills"
    communication = (root / "qbank/SKILL.md").read_text(encoding="utf-8")
    digitize_root = root / "qbank-digitize"
    digitize = (digitize_root / "SKILL.md").read_text(encoding="utf-8")
    _, yaml_text, _ = digitize.split("---", maxsplit=2)
    metadata = load_yaml(yaml_text)
    assert isinstance(metadata, dict)
    assert metadata["name"] == "qbank-digitize"
    assert "classification-table" in metadata["description"]
    assert "$qbank" in digitize
    assert "Do not redefine qbank commands" in digitize
    assert "$qbank-digitize" in communication
    assert "field_policy" not in communication
    assert "calibrated_batch" not in communication

    profile = load_yaml(
        (digitize_root / "assets/digitization-profile.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(profile, dict)
    assert profile["field_policy"]["chapter"]["mode"] == "ignore_as_null"
    assert profile["field_policy"]["difficulty"]["semantic"] is False
    assert profile["classification"]["unknown_policy"] == "review_required"
    assert profile["calibration"]["approval_required"] is True
    assert profile["execution_handoff"]["authorization"] == "dry_run_only"

    interface = load_yaml((digitize_root / "agents/openai.yaml").read_text(encoding="utf-8"))
    assert isinstance(interface, dict)
    assert "$qbank-digitize" in interface["interface"]["default_prompt"]
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
    assert result.integration_revision == 2
    assert result.context_protocol.target_project_root == str(root)
    assert result.context_protocol.execution_working_directory == str(root)
    assert result.context_protocol.required_handoff_fields == list(CONTEXT_REQUIRED_FIELDS)
    assert result.context_protocol.authorization_modes == list(CONTEXT_AUTHORIZATION_MODES)
    assert result.context_protocol.completion_handoff_fields == list(COMPLETION_HANDOFF_FIELDS)
    assert result.context_protocol.bootstrap_commands == [
        "qbank codex check --format json",
        "qbank codex instructions --format json",
    ]
    assert "Context handshake" in markdown
    assert "Do not infer a target project" in markdown
    assert "non-qbank source project as read-only" in markdown
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


def test_digitize_skill_installs_independently_from_communication_skill(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    home = tmp_path / "home"
    qbank_destination = home / ".agents/skills/qbank"
    digitize_destination = home / ".agents/skills/qbank-digitize"

    planned = install_repository_skill(
        context,
        dry_run=True,
        home=home,
        skill_name="qbank-digitize",
    )
    assert planned.action == "plan"
    assert planned.destination == str(digitize_destination)
    assert planned.files == len(DIGITIZE_SKILL_FILES)
    assert not qbank_destination.exists()
    assert not digitize_destination.exists()

    installed = install_repository_skill(
        context,
        dry_run=False,
        home=home,
        skill_name="qbank-digitize",
    )
    assert installed.action == "installed"
    assert not qbank_destination.exists()
    assert {
        path.relative_to(digitize_destination).as_posix(): path.read_bytes()
        for path in digitize_destination.rglob("*")
        if path.is_file()
    } == canonical_skill_contents("qbank-digitize")


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
) -> None:
    check = runner.invoke(app, ["codex", "check", "--format", "json"])
    assert check.exit_code == 0, check.output
    report = json.loads(check.stdout)
    assert report["ok"]
    assert report["repository_ready"]
    assert isinstance(report["codex_cli_ready"], bool)
    assert isinstance(report["degraded"], bool)
    assert report["integration_revision"] == INTEGRATION_REVISION
    assert any(item["name"] == "skill_frontmatter" for item in report["checks"])

    instructions = runner.invoke(app, ["codex", "instructions", "--format", "json"])
    assert instructions.exit_code == 0
    parsed = json.loads(instructions.stdout)
    assert parsed["paths"]["temporary_ai"] == "build/ai"
    assert parsed["context_protocol"]["target_project_root"] == str(cli_project)
    assert parsed["context_protocol"]["authorization_modes"] == [
        "read_only",
        "dry_run_only",
        "write_authorized",
    ]
    assert parsed["command_sequences"]["import"][1] == "qbank schema --format json"
    assert {workflow["name"] for workflow in parsed["workflows"]} >= {
        "import",
        "assets",
        "taxonomy",
        "maintenance",
    }

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
) -> None:
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

    invalid_skill = runner.invoke(
        app,
        ["codex", "install-skill", "--skill", "unknown", "--dry-run"],
    )
    assert invalid_skill.exit_code == 3
    assert "expected qbank or qbank-digitize" in invalid_skill.stderr


def test_digitize_skill_cli_selects_independent_source(
    runner: CliRunner,
    cli_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"

    def install(
        context: ProjectContext,
        *,
        dry_run: bool,
        scope: str = "user",
        update: bool = False,
        skill_name: str = "qbank",
    ) -> SkillInstallResult:
        return install_repository_skill(
            context,
            dry_run=dry_run,
            home=home,
            scope=cast(Any, scope),
            update=update,
            skill_name=cast(Any, skill_name),
        )

    monkeypatch.setattr("qbank.commands.codex.install_repository_skill", install)
    result = runner.invoke(
        app,
        [
            "codex",
            "install-skill",
            "--skill",
            "qbank-digitize",
            "--user",
            "--dry-run",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert Path(payload["destination"]).name == "qbank-digitize"
    assert payload["files"] == len(DIGITIZE_SKILL_FILES)
    assert not home.exists()


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


def test_codex_check_reports_project_skill_drift_without_failing_repository(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, config = project
    monkeypatch.chdir(root)
    reference = root / ".agents/skills/qbank/references/command-reference.md"
    reference.write_text(reference.read_text(encoding="utf-8") + "\ncustom\n", encoding="utf-8")
    monkeypatch.setattr("qbank.services.codex.shutil.which", lambda _name: None)

    result = check_codex_integration(
        ProjectContext.from_config(root, config),
        available_commands=set(REQUIRED_COMMANDS),
        user_skill=tmp_path / "missing-user-skill",
    )

    drift = next(check for check in result.checks if check.name == "project_skill_sync")
    assert result.ok and result.repository_ready
    assert result.degraded and not result.codex_cli_ready
    assert drift.status == "WARN"
    assert "1 modify" in drift.message


def test_codex_invalid_format_is_rejected_before_discovery(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_discovery() -> None:
        raise AssertionError("project discovery must not run")

    monkeypatch.setattr("qbank.commands.codex.discover_context", unexpected_discovery)
    result = runner.invoke(app, ["codex", "check", "--format", "yaml"])
    assert result.exit_code == 3
    assert "unsupported output format" in result.stderr


def test_codex_cli_check_uses_one_external_probe(
    runner: CliRunner,
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del cli_project
    calls: list[list[str]] = []

    def probe(command: list[str], **_kwargs: Any) -> Any:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="codex-cli 1.2.3", stderr="")

    monkeypatch.setattr("qbank.services.codex.shutil.which", lambda _name: "codex.exe")
    monkeypatch.setattr("qbank.services.codex.subprocess.run", probe)
    result = runner.invoke(app, ["codex", "check", "--format", "json"])
    report = json.loads(result.stdout)

    assert result.exit_code == 0
    assert report["codex_cli_ready"]
    assert len(calls) == 1
    assert calls[0] == ["codex.exe", "--version"]
    workflow = next(item for item in report["checks"] if item["name"] == "workflow_commands")
    assert workflow["status"] == "PASS"


def test_project_skill_update_is_dry_run_first_backed_up_and_atomic(
    project: tuple[Path, Any],
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    skill = root / ".agents/skills/qbank"
    reference = skill / "references/command-reference.md"
    original = reference.read_bytes() + b"\nlocal customization\n"
    reference.write_bytes(original)

    planned = install_repository_skill(
        context,
        dry_run=True,
        scope="project",
        update=True,
    )
    assert planned.action == "plan"
    assert planned.scope == "project"
    assert [(change.path, change.action) for change in planned.changes] == [
        ("references/command-reference.md", "modify")
    ]
    assert not (context.paths.state / "codex-skill-backups").exists()
    assert reference.read_bytes() == original

    committed = install_repository_skill(
        context,
        dry_run=False,
        scope="project",
        update=True,
    )
    assert committed.action == "updated"
    assert committed.backup is not None
    backup = Path(committed.backup)
    assert (backup / "references/command-reference.md").read_bytes() == original
    assert {
        path.relative_to(skill).as_posix(): path.read_bytes()
        for path in skill.rglob("*")
        if path.is_file()
    } == canonical_skill_contents()


def test_user_skill_update_keeps_project_source_and_backup(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    home = tmp_path / "home"
    installed = install_repository_skill(context, dry_run=False, home=home)
    destination = Path(installed.destination)
    skill_file = destination / "SKILL.md"
    stale = skill_file.read_bytes() + b"\nstale\n"
    skill_file.write_bytes(stale)

    planned = install_repository_skill(
        context,
        dry_run=True,
        home=home,
        update=True,
    )
    assert planned.changes[0].path == "SKILL.md"
    assert not (home / ".agents/.qbank-backups").exists()

    updated = install_repository_skill(
        context,
        dry_run=False,
        home=home,
        update=True,
    )
    assert updated.action == "updated"
    assert updated.backup is not None
    assert (Path(updated.backup) / "SKILL.md").read_bytes() == stale
    assert skill_file.read_bytes() == (root / ".agents/skills/qbank/SKILL.md").read_bytes()


def test_codex_check_reports_modified_optional_user_skill(
    project: tuple[Path, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    home = tmp_path / "home"
    installed = install_repository_skill(context, dry_run=False, home=home)
    user_skill = Path(installed.destination)
    (user_skill / "SKILL.md").write_text("modified", encoding="utf-8")
    monkeypatch.chdir(root)

    result = check_codex_integration(
        context,
        available_commands=set(REQUIRED_COMMANDS),
        user_skill=user_skill,
    )
    check = next(item for item in result.checks if item.name == "user_skill_sync")
    assert result.repository_ready
    assert result.degraded
    assert check.status == "WARN"


def test_skill_update_restores_original_when_commit_fails(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    reference = root / ".agents/skills/qbank/references/command-reference.md"
    original = reference.read_bytes() + b"\nkeep me\n"
    reference.write_bytes(original)
    real_replace = os.replace
    calls = 0

    class CommitFailure(OSError):
        pass

    def fail_commit(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CommitFailure("Skill commit failed")
        real_replace(source, destination)

    monkeypatch.setattr("qbank.services.codex.os.replace", fail_commit)
    with pytest.raises(CommitFailure, match="Skill commit failed"):
        install_repository_skill(
            context,
            dry_run=False,
            scope="project",
            update=True,
        )
    assert reference.read_bytes() == original


def test_skill_update_rollback_failure_preserves_commit_error(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    reference = root / ".agents/skills/qbank/references/command-reference.md"
    reference.write_text(reference.read_text(encoding="utf-8") + "\nchange\n", encoding="utf-8")
    real_replace = os.replace
    calls = 0

    class CommitFailure(OSError):
        pass

    def fail_commit_and_rollback(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CommitFailure("primary Skill commit failure")
        if calls == 3:
            raise OSError("backup restore failure")
        real_replace(source, destination)

    monkeypatch.setattr("qbank.services.codex.os.replace", fail_commit_and_rollback)
    with pytest.raises(CommitFailure, match="primary Skill commit failure") as captured:
        install_repository_skill(
            context,
            dry_run=False,
            scope="project",
            update=True,
        )
    assert any("rollback failed" in note for note in captured.value.__notes__)


def test_skill_install_rejects_symbolic_link_destination(
    project: tuple[Path, Any],
    tmp_path: Path,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)
    home = tmp_path / "home"
    destination = home / ".agents/skills/qbank"
    destination.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        destination.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symbolic links unavailable: {exc}")
    with pytest.raises(DataValidationError, match="symbolic link"):
        install_repository_skill(context, dry_run=True, home=home)


def test_project_skill_update_cli_json_is_pure_and_zero_write(
    runner: CliRunner,
    cli_project: Path,
) -> None:
    reference = cli_project / ".agents/skills/qbank/references/command-reference.md"
    original = reference.read_text(encoding="utf-8") + "\ncustom\n"
    reference.write_text(original, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "codex",
            "install-skill",
            "--project",
            "--update",
            "--dry-run",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["scope"] == "project"
    assert payload["dry_run"]
    assert payload["changes"] == [
        {
            "path": "references/command-reference.md",
            "action": "modify",
            "before_sha256": payload["changes"][0]["before_sha256"],
            "after_sha256": payload["changes"][0]["after_sha256"],
        }
    ]
    assert reference.read_text(encoding="utf-8") == original
