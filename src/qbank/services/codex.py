"""Repository-scoped Codex integration services without CLI dependencies."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

from qbank.context import ProjectContext
from qbank.errors import ConflictError, DataValidationError
from qbank.models import (
    CodexInstructionsResult,
    DoctorCheck,
    DoctorReport,
    DoctorSummary,
    SkillInstallResult,
)
from qbank.storage import split_frontmatter
from qbank.yaml_io import load_yaml

SKILL_DIRECTORY = Path(".agents/skills/qbank")
REQUIRED_WORKFLOW_COMMANDS = (
    ("doctor",),
    ("schema",),
    ("ingest",),
    ("validate",),
    ("preview",),
    ("query",),
    ("search",),
    ("get",),
    ("patch",),
    ("export",),
    ("paper", "validate"),
    ("paper", "build"),
)

CODEX_RULES = [
    "Markdown under questions/ is authoritative question data.",
    "JSON and JSONL are AI exchange formats; SQLite is only a rebuildable index.",
    "Read the question Schema before creating exchange data.",
    "Do not directly edit question Markdown or the SQLite index by default.",
    "Use add or ingest to create questions and patch to revise them.",
    "Dry-run every write, inspect diagnostics, then perform the write.",
    "Run validate with JSON output after every real write.",
    "Never silently overwrite an existing question ID.",
    "Keep uncertain questions draft and never invent answers or provenance.",
]

COMMAND_SEQUENCES = {
    "import": [
        "qbank doctor --format json",
        "qbank schema --format json",
        "qbank ingest build/ai/<job>.jsonl --dry-run --format json",
        "qbank ingest build/ai/<job>.jsonl --format json",
        "qbank validate --format json",
        "qbank preview",
    ],
    "revise": [
        "qbank query <filters> --format json",
        "qbank get <candidate-ids> --format json",
        "qbank patch ID --file PATCH --dry-run --format json",
        "qbank patch ID --file PATCH --format json",
        "qbank validate --format json",
    ],
    "select": [
        "qbank query <filters> --fields id,title,subject,chapter,topics,type,difficulty,status --format json",
        "qbank search <text> --format json",
        "qbank get <candidate-ids> --format json",
    ],
    "paper": [
        "qbank query <filters> --format json",
        "qbank get <candidate-ids> --format json",
        "qbank paper validate papers/generated/<paper>.yaml --format json",
        "qbank paper build papers/generated/<paper>.yaml --format md --output exports/<paper>-student.md",
        "qbank paper build papers/generated/<paper>.yaml --format md --with-solutions --output exports/<paper>-solutions.md",
    ],
}

CommandProbe = Callable[[tuple[str, ...]], bool]


def check_codex_integration(
    context: ProjectContext,
    *,
    command_probe: CommandProbe | None = None,
) -> DoctorReport:
    """Check repository instructions, Skill metadata, commands, and Codex availability."""
    probe = command_probe or _command_probe(context)
    checks = [
        _file_check("agents_md", context.root / "AGENTS.md"),
        _file_check("skill", context.root / SKILL_DIRECTORY / "SKILL.md"),
        _skill_frontmatter_check(context.root / SKILL_DIRECTORY / "SKILL.md"),
        _status_check(
            "qbank_executable",
            probe(()),
            "qbank is executable through the current Python environment",
            "qbank cannot be executed through the current Python environment",
        ),
        _working_directory_check(context),
        _codex_cli_check(),
        _workflow_commands_check(probe),
    ]
    failures = sum(check.status == "FAIL" for check in checks)
    warnings = sum(check.status == "WARN" for check in checks)
    return DoctorReport(
        ok=failures == 0,
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
    """Return deterministic repository rules, command sequences, and data paths."""
    return CodexInstructionsResult(
        ok=True,
        project_root=str(context.root),
        rules=list(CODEX_RULES),
        command_sequences={name: list(commands) for name, commands in COMMAND_SEQUENCES.items()},
        paths={
            "questions": _relative(context, context.paths.questions),
            "assets": _relative(context, context.paths.assets),
            "temporary_ai": _relative(context, context.paths.build / "ai"),
            "generated_papers": _relative(context, context.paths.papers / "generated"),
            "exports": _relative(context, context.paths.exports),
            "index": _relative(context, context.paths.state / "index.sqlite"),
        },
    )


def instructions_markdown(instructions: CodexInstructionsResult) -> str:
    """Render repository instructions as stable Markdown."""
    lines = [
        "# qbank Codex instructions",
        "",
        f"Project root: `{instructions.project_root}`",
        "",
        "## Rules",
        "",
        *(f"- {rule}" for rule in instructions.rules),
        "",
        "## Recommended command sequences",
        "",
    ]
    for name, commands in instructions.command_sequences.items():
        lines.extend((f"### {name}", "", "```powershell", *commands, "```", ""))
    lines.extend(("## Data paths", ""))
    lines.extend(f"- `{name}`: `{path}`" for name, path in instructions.paths.items())
    return "\n".join(lines).rstrip() + "\n"


def user_skill_destination(home: Path | None = None) -> Path:
    """Return the cross-platform user Skill installation path."""
    return (home or Path.home()).resolve() / ".agents" / "skills" / "qbank"


def install_repository_skill(
    context: ProjectContext,
    *,
    dry_run: bool,
    home: Path | None = None,
) -> SkillInstallResult:
    """Plan or atomically copy the repository Skill into the user Skill directory."""
    source = (context.root / SKILL_DIRECTORY).resolve()
    destination = user_skill_destination(home)
    _validate_skill_source(context, source)
    files = len([path for path in source.rglob("*") if path.is_file()])
    if destination.exists():
        if _tree_contents(source) == _tree_contents(destination):
            return _skill_install_result(
                source,
                destination,
                files,
                action="already_installed",
                dry_run=dry_run,
            )
        raise ConflictError(
            f"user Skill already exists with different content: {destination}; "
            "remove or back it up explicitly before installing"
        )
    if dry_run:
        return _skill_install_result(
            source,
            destination,
            files,
            action="plan",
            dry_run=True,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=".qbank-skill-",
            dir=destination.parent,
        )
    )
    staged = temporary_root / "qbank"
    try:
        shutil.copytree(source, staged)
        os.replace(staged, destination)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    return _skill_install_result(
        source,
        destination,
        files,
        action="installed",
        dry_run=False,
    )


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


def _working_directory_check(context: ProjectContext) -> DoctorCheck:
    current = Path.cwd().resolve()
    inside = current == context.root or current.is_relative_to(context.root)
    return _status_check(
        "working_directory",
        inside,
        f"inside qbank project: {current}",
        f"current working directory is outside qbank project: {current}",
    )


def _codex_cli_check() -> DoctorCheck:
    executable = shutil.which("codex")
    if not executable:
        return DoctorCheck(
            name="codex_cli",
            status="WARN",
            message="Codex CLI is not on PATH; qbank remains usable",
        )
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        error = type(exc).__name__
        winerror = getattr(exc, "winerror", None)
        if isinstance(winerror, int):
            error += f" (WinError {winerror})"
        return DoctorCheck(
            name="codex_cli",
            status="WARN",
            message=f"Codex CLI is on PATH but cannot be executed: {error}",
        )
    version = (result.stdout or result.stderr).strip()
    if result.returncode:
        return DoctorCheck(
            name="codex_cli",
            status="WARN",
            message=(
                f"Codex CLI is on PATH but returned {result.returncode}"
                + (f": {version}" if version else "")
            ),
        )
    return DoctorCheck(
        name="codex_cli",
        status="PASS",
        message=f"{executable}" + (f" ({version})" if version else ""),
    )


def _workflow_commands_check(probe: CommandProbe) -> DoctorCheck:
    missing = [" ".join(parts) for parts in REQUIRED_WORKFLOW_COMMANDS if not probe(parts)]
    return _status_check(
        "workflow_commands",
        not missing,
        f"{len(REQUIRED_WORKFLOW_COMMANDS)} required workflow commands are available",
        "missing command(s): " + ", ".join(missing),
    )


def _command_probe(context: ProjectContext) -> CommandProbe:
    def probe(parts: tuple[str, ...]) -> bool:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "qbank", *parts, "--help"],
                cwd=context.root,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    return probe


def _relative(context: ProjectContext, path: Path) -> str:
    return path.relative_to(context.root).as_posix()


def _validate_skill_source(context: ProjectContext, source: Path) -> None:
    if not source.is_dir() or not (source / "SKILL.md").is_file():
        raise DataValidationError(f"repository Skill is missing: {source}")
    if not source.is_relative_to(context.root):
        raise DataValidationError(f"repository Skill escapes project root: {source}")
    symlinks = [path for path in source.rglob("*") if path.is_symlink()]
    if symlinks:
        raise DataValidationError(f"repository Skill contains symbolic links: {symlinks[0]}")


def _tree_contents(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _skill_install_result(
    source: Path,
    destination: Path,
    files: int,
    *,
    action: str,
    dry_run: bool,
) -> SkillInstallResult:
    return SkillInstallResult.model_validate(
        {
            "ok": True,
            "dry_run": dry_run,
            "action": action,
            "source": str(source),
            "destination": str(destination),
            "files": files,
        }
    )
