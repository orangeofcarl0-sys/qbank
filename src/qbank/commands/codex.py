"""Codex repository-integration CLI adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, cast

import typer
from rich.table import Table

from qbank.cli_support import (
    abort,
    discover_context,
    emit_json,
    require_output_format,
    stdout_console,
)
from qbank.context import ProjectContext
from qbank.errors import DataValidationError, ExitCode
from qbank.models import McpConfigChange, SkillInstallResult
from qbank.services.codex import (
    check_codex_integration,
    codex_instructions,
    install_repository_skill,
    instructions_markdown,
)
from qbank.services.mcp_config import (
    install_project_mcp,
    mcp_integration_status,
    uninstall_project_mcp,
)


def codex_mcp_check_command(
    output_format: Annotated[str, typer.Option("--format", metavar="table|json")] = "table",
) -> None:
    """Check optional MCP runtime and this project's exact registration."""
    try:
        require_output_format(output_format, "table", "json")
        result = mcp_integration_status(discover_context())
        if output_format == "json":
            emit_json(result)
        else:
            typer.echo("READY" if result.ok else "DEGRADED")
            typer.echo(result.message)
            typer.echo(f"Configuration: {result.configuration}")
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.GENERAL))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def codex_integration_status_command(
    output_format: Annotated[str, typer.Option("--format", metavar="table|json")] = "table",
) -> None:
    """Report MCP readiness without treating an absent Codex CLI as qbank failure."""
    try:
        require_output_format(output_format, "table", "json")
        result = mcp_integration_status(discover_context())
        if output_format == "json":
            emit_json(result)
        else:
            typer.echo("READY" if not result.degraded else "DEGRADED")
            typer.echo(result.message)
    except Exception as exc:
        abort(exc, output_format=output_format)


def codex_install_mcp_command(
    project: Annotated[
        bool, typer.Option("--project", help="Write only .codex/config.toml here.")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Inspect without writing.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm the project write.")] = False,
    output_format: Annotated[str, typer.Option("--format", metavar="table|json")] = "table",
) -> None:
    """Install the repository-bound qbank MCP registration for this project."""
    _mcp_config_command(project, dry_run, yes, output_format, uninstall=False)


def codex_uninstall_mcp_command(
    project: Annotated[bool, typer.Option("--project", help="Modify only this project.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Inspect without writing.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Confirm the project write.")] = False,
    output_format: Annotated[str, typer.Option("--format", metavar="table|json")] = "table",
) -> None:
    """Remove only qbank's managed MCP block from this project."""
    _mcp_config_command(project, dry_run, yes, output_format, uninstall=True)


def _mcp_config_command(
    project: bool,
    dry_run: bool,
    yes: bool,
    output_format: str,
    *,
    uninstall: bool,
) -> None:
    try:
        require_output_format(output_format, "table", "json")
        if not project:
            raise DataValidationError("MCP registration requires explicit --project")
        context = discover_context()
        operation = uninstall_project_mcp if uninstall else install_project_mcp
        planned = operation(context, dry_run=True)
        if dry_run or not planned.changed:
            _emit_mcp_change(planned, output_format)
            return
        if output_format == "json" and not yes:
            raise DataValidationError("JSON MCP writes require explicit --yes authorization")
        if not yes and not typer.confirm(f"{planned.action.title()} qbank MCP in this project?"):
            raise typer.Exit(code=int(ExitCode.GENERAL))
        _emit_mcp_change(operation(context, dry_run=False), output_format)
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def _emit_mcp_change(result: McpConfigChange, output_format: str) -> None:
    if output_format == "json":
        emit_json(result)
        return
    typer.echo(f"{result.action}: {result.configuration}")
    typer.echo(f"Repository: {result.repository}")
    if result.backup:
        typer.echo(f"Backup: {result.backup}")


def codex_check_command(
    context: typer.Context,
    output_format: Annotated[
        str,
        typer.Option("--format", metavar="table|json"),
    ] = "table",
) -> None:
    """Check repository instructions, Skill discovery, and required commands."""
    try:
        require_output_format(output_format, "table", "json")
        result = check_codex_integration(
            discover_context(),
            available_commands=_registered_command_paths(context),
        )
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            table = Table("Status", "Check", "Details")
            for check in result.checks:
                table.add_row(check.status, check.name, check.message)
            stdout_console.print(table)
            state = "ready" if not result.degraded else "degraded"
            typer.echo(
                f"Repository: {state}; Codex CLI: "
                f"{'ready' if result.codex_cli_ready else 'unavailable'}"
            )
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.GENERAL))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def codex_instructions_command(
    output_format: Annotated[
        str,
        typer.Option("--format", metavar="markdown|json"),
    ] = "markdown",
) -> None:
    """Print repository AI rules, recommended sequences, and stable data paths."""
    try:
        if output_format not in {"markdown", "json"}:
            raise DataValidationError("unsupported output format: expected markdown or json")
        result = codex_instructions(discover_context())
        if output_format == "json":
            emit_json(result)
        elif output_format == "markdown":
            typer.echo(instructions_markdown(result), nl=False)
    except Exception as exc:
        abort(exc, output_format="json" if output_format == "json" else "table")


def codex_install_skill_command(
    skill_name: Annotated[
        str,
        typer.Option(
            "--skill",
            metavar="qbank|qbank-digitize|qbank-deliver",
            help="Select one Skill.",
        ),
    ] = "qbank",
    user: Annotated[
        bool,
        typer.Option(
            "--user",
            help="Explicitly select the default current-user Skill scope.",
        ),
    ] = False,
    project: Annotated[
        bool,
        typer.Option("--project", help="Install the packaged Skill into this project."),
    ] = False,
    update: Annotated[
        bool,
        typer.Option("--update", help="Allow an inspected, backed-up replacement."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show the installation plan without writing."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", metavar="table|json"),
    ] = "table",
) -> None:
    """Install or explicitly update one qbank Skill for a selected scope."""
    try:
        require_output_format(output_format, "table", "json")
        if skill_name not in {"qbank", "qbank-digitize", "qbank-deliver"}:
            raise DataValidationError(
                "unsupported Skill: expected qbank, qbank-digitize, or qbank-deliver"
            )
        if user and project:
            raise DataValidationError("choose only one of --user or --project")
        scope: Literal["user", "project"] = "project" if project else "user"
        context = discover_context()
        selected = cast(Literal["qbank", "qbank-digitize", "qbank-deliver"], skill_name)
        planned = _install_skill(
            context,
            dry_run=True,
            scope=scope,
            update=update,
            skill_name=selected,
        )
        if dry_run:
            _emit_skill_result(planned, output_format)
            return
        if planned.action == "already_installed":
            _emit_skill_result(planned, output_format)
            return
        if output_format == "json" and not yes:
            raise DataValidationError("JSON Skill writes require explicit --yes authorization")
        if output_format == "table":
            _print_skill_plan(planned)
        label = "this Skill" if skill_name == "qbank" else skill_name
        if not yes and not typer.confirm(f"Install {label} for the {scope} scope?"):
            raise typer.Exit(code=int(ExitCode.GENERAL))
        result = _install_skill(
            context,
            dry_run=False,
            scope=scope,
            update=update,
            skill_name=selected,
        )
        _emit_skill_result(result, output_format)
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def _registered_command_paths(context: typer.Context) -> set[tuple[str, ...]]:
    """Return the current Click command tree without spawning subprocesses."""
    root = context.find_root().command
    result: set[tuple[str, ...]] = set()

    def visit(command: object, prefix: tuple[str, ...]) -> None:
        raw_children = getattr(command, "commands", None)
        if not isinstance(raw_children, Mapping):
            return
        children = cast(Mapping[str, object], raw_children)
        for name, child in children.items():
            path = (*prefix, name)
            result.add(path)
            visit(child, path)

    visit(root, ())
    return result


def _install_skill(
    context: ProjectContext,
    *,
    dry_run: bool,
    scope: Literal["user", "project"],
    update: bool,
    skill_name: Literal["qbank", "qbank-digitize", "qbank-deliver"],
) -> SkillInstallResult:
    if skill_name == "qbank" and scope == "user" and not update:
        return install_repository_skill(context, dry_run=dry_run)
    if skill_name == "qbank" and scope == "project":
        return install_repository_skill(
            context,
            dry_run=dry_run,
            scope=scope,
            update=update,
        )
    return install_repository_skill(
        context,
        dry_run=dry_run,
        scope=scope,
        update=update,
        skill_name=skill_name,
    )


def _emit_skill_result(result: SkillInstallResult, output_format: str) -> None:
    if output_format == "json":
        emit_json(result)
        return
    _print_skill_plan(result)


def _print_skill_plan(result: SkillInstallResult) -> None:
    if result.dry_run:
        typer.echo(f"Dry-run ({result.scope}): {result.source}")
    else:
        typer.echo(f"{result.action}: {result.destination} ({result.files} files)")
        typer.echo(f"Source ({result.scope}): {result.source}")
    typer.echo(f"Destination: {result.destination}")
    for change in result.changes:
        typer.echo(f"  {change.action}: {change.path}")
    if result.backup:
        typer.echo(f"Backup: {result.backup}")
    typer.echo(f"{result.files} files; action={result.action}")
