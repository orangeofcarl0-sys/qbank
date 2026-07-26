"""Repository-scoped Codex integration services without CLI dependencies."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from qbank.codex_manifest import (
    CODEX_RULES,
    COMPLETION_HANDOFF_FIELDS,
    CONTEXT_AUTHORIZATION_MODES,
    CONTEXT_REQUIRED_FIELDS,
    DELIVER_SKILL_FILES,
    DIGITIZE_SKILL_FILES,
    FOREIGN_PROJECT_POLICY,
    INTEGRATION_CAPABILITIES,
    INTEGRATION_REVISION,
    LEGACY_COMMAND_SEQUENCES,
    REQUIRED_COMMANDS,
    SKILL_FILES,
    WORKFLOWS,
)
from qbank.context import ProjectContext
from qbank.errors import ConflictError, DataValidationError
from qbank.models import (
    CodexCapability,
    CodexCheckReport,
    CodexCliCandidate,
    CodexContextProtocol,
    CodexInstructionsResult,
    CodexWorkflow,
    DoctorCheck,
    DoctorSummary,
    SkillFileChange,
    SkillInstallResult,
)
from qbank.storage import split_frontmatter
from qbank.yaml_io import load_yaml

SKILL_DIRECTORY = Path(".agents/skills/qbank")
REQUIRED_WORKFLOW_COMMANDS = REQUIRED_COMMANDS
SkillScope = Literal["user", "project"]
SkillName = Literal["qbank", "qbank-digitize", "qbank-deliver"]
CommandProbe = Callable[[tuple[str, ...]], bool]


@dataclass(frozen=True, slots=True)
class _SkillOutcome:
    scope: SkillScope
    action: Literal["plan", "installed", "updated", "already_installed"]
    dry_run: bool
    backup: str | None = None


@dataclass(frozen=True, slots=True)
class _SkillSelection:
    scope: SkillScope
    home: Path | None
    name: SkillName


def check_codex_integration(
    context: ProjectContext,
    *,
    command_probe: CommandProbe | None = None,
    available_commands: set[tuple[str, ...]] | None = None,
    user_skill: Path | None = None,
) -> CodexCheckReport:
    """Check project instructions, active Skills, commands, and Codex availability."""
    project_skill = context.root / SKILL_DIRECTORY
    canonical = canonical_skill_contents()
    if command_probe is None:
        inventory = available_commands if available_commands is not None else set(REQUIRED_COMMANDS)
        executable_ok = True
        workflow_check = _workflow_inventory_check(inventory)
    else:
        executable_ok = command_probe(())
        workflow_check = _workflow_probe_check(command_probe)
    codex_cli, codex_candidates = _codex_cli_check(context)
    checks = [
        _file_check("agents_md", context.root / "AGENTS.md"),
        _file_check("skill", project_skill / "SKILL.md"),
        _skill_frontmatter_check(project_skill / "SKILL.md"),
        _skill_sync_check(
            "project_skill_sync",
            project_skill,
            canonical,
            optional=False,
        ),
        _status_check(
            "qbank_executable",
            executable_ok,
            "qbank is executable through the current Python environment",
            "qbank cannot be executed through the current Python environment",
        ),
        _working_directory_check(context),
        codex_cli,
        _skill_sync_check(
            "user_skill_sync",
            user_skill or user_skill_destination(),
            _safe_project_skill_contents(project_skill),
            optional=True,
        ),
        workflow_check,
    ]
    failures = sum(check.status == "FAIL" for check in checks)
    warnings = sum(check.status == "WARN" for check in checks)
    repository_ready = failures == 0
    return CodexCheckReport(
        ok=repository_ready,
        repository_ready=repository_ready,
        codex_cli_ready=codex_cli.status == "PASS",
        degraded=failures > 0 or warnings > 0,
        integration_revision=INTEGRATION_REVISION,
        codex_cli_candidates=codex_candidates,
        summary=DoctorSummary(
            **{
                "pass": len(checks) - failures - warnings,
                "warn": warnings,
                "fail": failures,
            }
        ),
        checks=checks,
    )


def codex_instructions(context: ProjectContext) -> CodexInstructionsResult:
    """Return deterministic repository rules, workflows, commands, and data paths."""
    return CodexInstructionsResult(
        ok=True,
        project_root=str(context.root),
        rules=list(CODEX_RULES),
        command_sequences={
            name: list(commands) for name, commands in LEGACY_COMMAND_SEQUENCES.items()
        },
        paths={
            "questions": _relative(context, context.paths.questions),
            "assets": _relative(context, context.paths.assets),
            "temporary_ai": _relative(context, context.paths.build / "ai"),
            "generated_papers": _relative(context, context.paths.papers / "generated"),
            "exports": _relative(context, context.paths.exports),
            "index": _relative(context, context.paths.state / "index.sqlite"),
        },
        integration_revision=INTEGRATION_REVISION,
        context_protocol=CodexContextProtocol(
            target_project_root=str(context.root),
            execution_working_directory=str(context.root),
            required_handoff_fields=list(CONTEXT_REQUIRED_FIELDS),
            authorization_modes=list(CONTEXT_AUTHORIZATION_MODES),
            foreign_project_policy=FOREIGN_PROJECT_POLICY,
            bootstrap_commands=[
                "qbank codex check --format json",
                "qbank codex instructions --format json",
            ],
            completion_handoff_fields=list(COMPLETION_HANDOFF_FIELDS),
        ),
        workflows=[
            CodexWorkflow.model_validate(
                {
                    "name": workflow.name,
                    "title": workflow.title,
                    "purpose": workflow.purpose,
                    "preconditions": workflow.preconditions,
                    "steps": [
                        {
                            "command": step.command,
                            "description": step.description,
                            "command_path": step.command_path,
                            "writes": step.writes,
                            "dry_run_required": step.dry_run_required,
                            "explicit_authorization": step.explicit_authorization,
                            "interactive": step.interactive,
                            "expected": step.expected,
                        }
                        for step in workflow.steps
                    ],
                }
            )
            for workflow in WORKFLOWS
        ],
        capabilities=[
            CodexCapability(
                name=capability.name,
                workflow=capability.workflow,
                cli_command=(
                    list(capability.cli_command) if capability.cli_command is not None else None
                ),
                mcp_tool=capability.mcp_tool,
                resource=capability.resource,
                access=cast(Literal["read", "prepare", "write"], capability.access),
                schema_version=capability.schema_version,
            )
            for capability in INTEGRATION_CAPABILITIES
        ],
    )


def instructions_markdown(instructions: CodexInstructionsResult) -> str:
    """Render repository instructions as stable Markdown."""
    lines = [
        "# qbank Codex instructions",
        "",
        f"Project root: `{instructions.project_root}`",
        f"Integration revision: `{instructions.integration_revision}`",
        "",
        "## Context handshake",
        "",
        "Run qbank commands with the target project as the working directory.",
        "Do not infer a target project or write scope from earlier conversation.",
        "",
        "Required task context:",
        "",
        *(f"- `{field}`" for field in instructions.context_protocol.required_handoff_fields),
        "",
        "Authorization modes: "
        + ", ".join(f"`{mode}`" for mode in instructions.context_protocol.authorization_modes),
        "",
        f"Foreign-project policy: {instructions.context_protocol.foreign_project_policy}",
        "",
        "Bootstrap commands:",
        "",
        *(f"- `{command}`" for command in instructions.context_protocol.bootstrap_commands),
        "",
        "## Rules",
        "",
        *(f"- {rule}" for rule in instructions.rules),
        "",
        "## Recommended workflows",
        "",
    ]
    for workflow in instructions.workflows:
        lines.extend((f"### {workflow.name} — {workflow.title}", "", workflow.purpose, ""))
        if workflow.preconditions:
            lines.extend(("Prerequisites:", ""))
            lines.extend(f"- {item}" for item in workflow.preconditions)
            lines.append("")
        for index, step in enumerate(workflow.steps, start=1):
            flags: list[str] = []
            if step.writes:
                flags.append("writes")
            if step.dry_run_required:
                flags.append("dry-run")
            if step.explicit_authorization:
                flags.append("explicit authorization")
            if step.interactive:
                flags.append("interactive")
            suffix = f" ({', '.join(flags)})" if flags else ""
            lines.extend(
                (
                    f"{index}. `{step.command}`{suffix}",
                    f"   {step.description}",
                )
            )
            if step.expected:
                lines.append(f"   Expected: {step.expected}")
        lines.append("")
    lines.extend(_capability_lines(instructions.capabilities))
    lines.extend(
        (
            "## Placeholders and recovery",
            "",
            "- Replace values such as `<filters>`, `<id>`, and `<paper>` with explicit user scope.",
            "- Exit code 3 means validation failed; fix the input before retrying.",
            "- Exit code 5 means a conflict; never bypass it by overwriting authoritative data.",
            "- If search reports a missing, dirty, corrupt, or stale index, rebuild it only when authorized.",
            "- Never launch `qbank preview --serve` or `qbank desktop` in unattended automation.",
            "",
            "## Data paths",
            "",
        )
    )
    lines.extend(f"- `{name}`: `{path}`" for name, path in instructions.paths.items())
    return "\n".join(lines).rstrip() + "\n"


def _capability_lines(capabilities: list[CodexCapability]) -> list[str]:
    lines = ["## Interface capabilities", ""]
    for capability in capabilities:
        interfaces: list[str] = []
        if capability.cli_command:
            interfaces.append(f"CLI: qbank {' '.join(capability.cli_command)}")
        if capability.mcp_tool:
            interfaces.append(f"MCP: {capability.mcp_tool}")
        if capability.resource:
            interfaces.append(f"resource: {capability.resource}")
        lines.append(
            f"- `{capability.name}` [{capability.access}; schema "
            f"{capability.schema_version}] — {'; '.join(interfaces)}"
        )
    lines.append("")
    return lines


def user_skill_destination(home: Path | None = None) -> Path:
    """Return the cross-platform user Skill installation path."""
    return user_named_skill_destination("qbank", home=home)


def user_named_skill_destination(
    skill_name: SkillName,
    *,
    home: Path | None = None,
) -> Path:
    """Return the user installation path for one bundled qbank Skill."""
    return (home or Path.home()).resolve() / ".agents" / "skills" / skill_name


def install_repository_skill(
    context: ProjectContext,
    *,
    dry_run: bool,
    home: Path | None = None,
    scope: SkillScope = "user",
    update: bool = False,
    skill_name: SkillName = "qbank",
) -> SkillInstallResult:
    """Plan, install, or explicitly update a project or user qbank Skill."""
    selection = _SkillSelection(scope, home, skill_name)
    source, source_label, destination = _skill_endpoints(context, selection)
    expected = source if isinstance(source, dict) else _validated_tree(context, source)
    _validate_destination(destination)
    exists = destination.exists()
    current = _tree_contents(destination) if exists else {}
    changes = _skill_changes(current, expected)
    if exists and not changes:
        return _skill_install_result(
            source_label,
            destination,
            len(expected),
            [],
            _SkillOutcome(scope, "already_installed", dry_run),
        )
    if exists and not update:
        raise ConflictError(
            f"{scope} Skill already exists with different content: {destination}; "
            "inspect the diff with --update --dry-run before replacing it"
        )
    if dry_run:
        return _skill_install_result(
            source_label,
            destination,
            len(expected),
            changes,
            _SkillOutcome(scope, "plan", True),
        )
    backup = _replace_skill_tree(
        context,
        destination,
        expected,
        update=exists,
        selection=selection,
    )
    return _skill_install_result(
        source_label,
        destination,
        len(expected),
        changes,
        _SkillOutcome(
            scope,
            "updated" if exists else "installed",
            False,
            backup,
        ),
    )


def canonical_skill_contents(skill_name: SkillName = "qbank") -> dict[str, bytes]:
    """Read one packaged canonical Skill tree in source and wheel installations."""
    directory, skill_files = {
        "qbank": ("skill", SKILL_FILES),
        "qbank-digitize": ("qbank-digitize", DIGITIZE_SKILL_FILES),
        "qbank-deliver": ("qbank-deliver", DELIVER_SKILL_FILES),
    }[skill_name]
    root = files("qbank.resources").joinpath("init", "codex", directory)
    return {
        relative: root.joinpath(*PurePosixPath(relative).parts)
        .read_text(encoding="utf-8")
        .encode("utf-8")
        for relative in skill_files
    }


def _skill_endpoints(
    context: ProjectContext,
    selection: _SkillSelection,
) -> tuple[Path | dict[str, bytes], str, Path]:
    if selection.scope == "user":
        source = context.root / ".agents" / "skills" / selection.name
        destination = user_named_skill_destination(selection.name, home=selection.home)
        return source, str(source), destination
    if selection.scope == "project":
        return (
            canonical_skill_contents(selection.name),
            "package:qbank.resources/init/codex/"
            f"{'skill' if selection.name == 'qbank' else selection.name}",
            context.root / ".agents" / "skills" / selection.name,
        )
    raise DataValidationError(f"unsupported Skill scope: {selection.scope}")


def _validated_tree(context: ProjectContext, source: Path) -> dict[str, bytes]:
    _validate_skill_source(context, source)
    return _tree_contents(source)


def _replace_skill_tree(
    context: ProjectContext,
    destination: Path,
    contents: Mapping[str, bytes],
    *,
    update: bool,
    selection: _SkillSelection,
) -> str | None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".qbank-skill-", dir=destination.parent))
    staged = temporary_root / "qbank"
    backup: Path | None = None
    moved_original = False
    try:
        _write_tree(staged, contents)
        if update:
            backup = _backup_destination(context, selection)
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(destination, backup)
            moved_original = True
        try:
            os.replace(staged, destination)
        except Exception as original_error:
            if moved_original and backup is not None:
                try:
                    if destination.exists():
                        shutil.rmtree(destination)
                    os.replace(backup, destination)
                except Exception as rollback_error:
                    original_error.add_note(f"rollback failed: {rollback_error}")
            raise
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return str(backup) if backup is not None else None


def _backup_destination(
    context: ProjectContext,
    selection: _SkillSelection,
) -> Path:
    token = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    if selection.scope == "project":
        root = context.paths.state / "codex-skill-backups"
        if selection.name != "qbank":
            root /= selection.name
    else:
        root = (
            (selection.home or Path.home()).resolve()
            / ".agents"
            / ".qbank-backups"
            / "skills"
            / selection.name
        )
    return root / token


def _write_tree(root: Path, contents: Mapping[str, bytes]) -> None:
    for relative, content in sorted(contents.items()):
        destination = root.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def _file_check(name: str, path: Path) -> DoctorCheck:
    return _status_check(name, path.is_file(), str(path), f"missing: {path}")


def _status_check(name: str, ok: bool, success: str, failure: str) -> DoctorCheck:
    return DoctorCheck(
        name=name,
        status="PASS" if ok else "FAIL",
        message=success if ok else failure,
    )


def _skill_frontmatter_check(path: Path) -> DoctorCheck:
    if not path.is_file():
        return DoctorCheck(name="skill_frontmatter", status="FAIL", message=f"missing: {path}")
    try:
        yaml_text, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        raw = load_yaml(yaml_text)
    except (OSError, UnicodeError, ValueError, DataValidationError) as exc:
        return DoctorCheck(name="skill_frontmatter", status="FAIL", message=str(exc))
    mapping = cast(dict[str, object], raw) if isinstance(raw, dict) else {}
    name = mapping.get("name")
    description = mapping.get("description")
    valid = (
        name == "qbank"
        and isinstance(description, str)
        and bool(description.strip())
        and set(mapping) == {"name", "description"}
    )
    return _status_check(
        "skill_frontmatter",
        valid,
        "valid qbank Skill frontmatter",
        "frontmatter must contain only non-empty name=qbank and description fields",
    )


def _skill_sync_check(
    name: str,
    path: Path,
    expected: Mapping[str, bytes],
    *,
    optional: bool,
) -> DoctorCheck:
    if path.is_symlink() or (path.exists() and any(item.is_symlink() for item in path.rglob("*"))):
        return DoctorCheck(
            name=name,
            status="WARN" if optional else "FAIL",
            message=f"Skill contains symbolic links and cannot be trusted: {path}",
        )
    if not path.is_dir():
        if path.exists():
            return DoctorCheck(
                name=name,
                status="WARN" if optional else "FAIL",
                message=f"Skill path is not a directory: {path}",
            )
        return DoctorCheck(
            name=name,
            status="PASS" if optional else "FAIL",
            message=(
                f"optional user Skill is not installed: {path}"
                if optional
                else f"project Skill is missing: {path}"
            ),
        )
    try:
        changes = _skill_changes(_tree_contents(path), expected)
    except OSError as exc:
        return DoctorCheck(
            name=name,
            status="WARN" if optional else "FAIL",
            message=f"cannot inspect Skill: {exc}",
        )
    if not changes:
        return DoctorCheck(name=name, status="PASS", message=f"Skill is current: {path}")
    counts = {action: 0 for action in ("add", "modify", "delete")}
    for change in changes:
        counts[change.action] += 1
    return DoctorCheck(
        name=name,
        status="WARN",
        message=(
            f"Skill differs from its expected source: {path} "
            f"({counts['add']} add, {counts['modify']} modify, {counts['delete']} delete); "
            "inspect qbank codex install-skill --update --dry-run"
        ),
    )


def _safe_project_skill_contents(path: Path) -> dict[str, bytes]:
    if not path.is_dir() or path.is_symlink():
        return canonical_skill_contents()
    try:
        return _tree_contents(path)
    except OSError:
        return canonical_skill_contents()


def _working_directory_check(context: ProjectContext) -> DoctorCheck:
    current = Path.cwd().resolve()
    inside = current == context.root or current.is_relative_to(context.root)
    return _status_check(
        "working_directory",
        inside,
        f"inside qbank project: {current}",
        f"current working directory is outside qbank project: {current}",
    )


def probe_codex_cli(context: ProjectContext) -> tuple[list[CodexCliCandidate], str | None]:
    """Probe every distinct local candidate and select the first runnable CLI."""
    candidates: list[CodexCliCandidate] = []
    selected: str | None = None
    for executable, source in _codex_cli_candidates(context):
        try:
            result = subprocess.run(
                _codex_probe_command(executable),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except PermissionError as exc:
            candidate = CodexCliCandidate(
                path=executable,
                source=source,
                status="denied",
                failure_reason=_probe_error(exc),
            )
        except subprocess.TimeoutExpired as exc:
            candidate = CodexCliCandidate(
                path=executable,
                source=source,
                status="timeout",
                failure_reason=_probe_error(exc),
            )
        except OSError as exc:
            candidate = CodexCliCandidate(
                path=executable,
                source=source,
                status="failed",
                failure_reason=_probe_error(exc),
            )
        else:
            version = (result.stdout or result.stderr).strip() or None
            if result.returncode:
                candidate = CodexCliCandidate(
                    path=executable,
                    source=source,
                    status="failed",
                    version=version,
                    failure_reason=f"exit code {result.returncode}",
                )
            else:
                candidate = CodexCliCandidate(
                    path=executable,
                    source=source,
                    status="ready",
                    version=version,
                    selected=selected is None,
                )
                if selected is None:
                    selected = executable
        candidates.append(candidate)
    return candidates, selected


def _codex_cli_check(
    context: ProjectContext,
) -> tuple[DoctorCheck, list[CodexCliCandidate]]:
    candidates, selected = probe_codex_cli(context)
    if not candidates:
        return (
            DoctorCheck(
                name="codex_cli",
                status="WARN",
                message="Codex CLI was not found; repository Skill clients remain usable",
            ),
            candidates,
        )
    if selected is None:
        summary = "; ".join(
            f"{item.path}: {item.failure_reason or item.status}" for item in candidates
        )
        return (
            DoctorCheck(
                name="codex_cli",
                status="WARN",
                message=f"Codex CLI candidates cannot be executed: {summary}",
            ),
            candidates,
        )
    chosen = next(item for item in candidates if item.selected)
    return (
        DoctorCheck(
            name="codex_cli",
            status="PASS",
            message=f"{chosen.path}" + (f" ({chosen.version})" if chosen.version else ""),
        ),
        candidates,
    )


def _codex_cli_candidates(context: ProjectContext) -> list[tuple[str, str]]:
    raw: list[tuple[str | None, str]] = [
        (os.environ.get("CODEX_CLI"), "CODEX_CLI"),
        (shutil.which("codex"), "PATH:codex"),
    ]
    if os.name == "nt":
        raw.extend(
            (
                (shutil.which("codex.cmd"), "PATH:codex.cmd"),
                (
                    _existing_candidate(Path(os.environ.get("APPDATA", "")) / "npm/codex.cmd"),
                    "npm-user",
                ),
                (
                    _existing_candidate(
                        context.root / "build/codex-cli/node_modules/.bin/codex.cmd"
                    ),
                    "npm-workspace",
                ),
                (
                    _existing_candidate(
                        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WindowsApps/codex.exe"
                    ),
                    "windows-app-alias",
                ),
            )
        )
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value, source in raw:
        if not value:
            continue
        key = os.path.normcase(os.path.abspath(value))
        if key in seen:
            continue
        seen.add(key)
        result.append((value, source))
    return result


def _existing_candidate(path: Path) -> str | None:
    return str(path) if path.is_file() else None


def _codex_probe_command(executable: str) -> list[str]:
    if os.name == "nt" and Path(executable).suffix.casefold() in {".cmd", ".bat"}:
        command = os.environ.get("COMSPEC", "cmd.exe")
        return [command, "/d", "/s", "/c", f'""{executable}" --version"']
    return [executable, "--version"]


def _probe_error(exc: BaseException) -> str:
    message = type(exc).__name__
    winerror = getattr(exc, "winerror", None)
    if isinstance(winerror, int):
        message += f" (WinError {winerror})"
    return message


def _workflow_inventory_check(available: set[tuple[str, ...]]) -> DoctorCheck:
    missing = [" ".join(parts) for parts in REQUIRED_COMMANDS if parts not in available]
    return _workflow_status(missing)


def _workflow_probe_check(probe: CommandProbe) -> DoctorCheck:
    missing = [" ".join(parts) for parts in REQUIRED_COMMANDS if not probe(parts)]
    return _workflow_status(missing)


def _workflow_status(missing: list[str]) -> DoctorCheck:
    return _status_check(
        "workflow_commands",
        not missing,
        f"{len(REQUIRED_COMMANDS)} required workflow commands are available",
        "missing command(s): " + ", ".join(missing),
    )


def _relative(context: ProjectContext, path: Path) -> str:
    return path.relative_to(context.root).as_posix()


def _validate_skill_source(context: ProjectContext, source: Path) -> None:
    if not source.is_dir() or not (source / "SKILL.md").is_file():
        raise DataValidationError(f"repository Skill is missing: {source}")
    resolved = source.resolve()
    if not resolved.is_relative_to(context.root):
        raise DataValidationError(f"repository Skill escapes project root: {resolved}")
    symlinks = [path for path in (source, *source.rglob("*")) if path.is_symlink()]
    if symlinks:
        raise DataValidationError(f"repository Skill contains symbolic links: {symlinks[0]}")


def _validate_destination(destination: Path) -> None:
    if destination.is_symlink():
        raise DataValidationError(f"Skill destination is a symbolic link: {destination}")
    if destination.exists():
        if not destination.is_dir():
            raise DataValidationError(f"Skill destination is not a directory: {destination}")
        symlinks = [path for path in destination.rglob("*") if path.is_symlink()]
        if symlinks:
            raise DataValidationError(f"Skill destination contains symbolic links: {symlinks[0]}")


def _tree_contents(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _skill_changes(
    before: Mapping[str, bytes],
    after: Mapping[str, bytes],
) -> list[SkillFileChange]:
    result: list[SkillFileChange] = []
    for relative in sorted(set(before) | set(after)):
        old = before.get(relative)
        new = after.get(relative)
        if old == new:
            continue
        action: Literal["add", "modify", "delete"]
        if old is None:
            action = "add"
        elif new is None:
            action = "delete"
        else:
            action = "modify"
        result.append(
            SkillFileChange(
                path=relative,
                action=action,
                before_sha256=_sha256(old),
                after_sha256=_sha256(new),
            )
        )
    return result


def _sha256(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _skill_install_result(
    source: str,
    destination: Path,
    files_count: int,
    changes: list[SkillFileChange],
    outcome: _SkillOutcome,
) -> SkillInstallResult:
    return SkillInstallResult(
        ok=True,
        dry_run=outcome.dry_run,
        action=outcome.action,
        source=source,
        destination=str(destination),
        files=files_count,
        scope=outcome.scope,
        backup=outcome.backup,
        changes=changes,
    )
