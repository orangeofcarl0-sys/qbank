"""Codex repository-integration CLI adapters."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from qbank.cli_support import (
    abort,
    discover_context,
    emit_json,
    stdout_console,
)
from qbank.errors import DataValidationError, ExitCode
from qbank.services.codex import (
    check_codex_integration,
    codex_instructions,
    install_repository_skill,
    instructions_markdown,
    user_skill_destination,
)


def codex_check_command(
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Check repository instructions, Skill discovery, and required commands."""
    try:
        result = check_codex_integration(discover_context())
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            table = Table("Status", "Check", "Details")
            for check in result.checks:
                table.add_row(check.status, check.name, check.message)
            stdout_console.print(table)
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.GENERAL))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def codex_instructions_command(
    output_format: Annotated[str, typer.Option("--format")] = "markdown",
) -> None:
    """Print repository AI rules, recommended sequences, and stable data paths."""
    try:
        result = codex_instructions(discover_context())
        if output_format == "json":
            emit_json(result)
        elif output_format == "markdown":
            typer.echo(instructions_markdown(result), nl=False)
        else:
            raise DataValidationError("unsupported output format: expected markdown or json")
    except Exception as exc:
        abort(exc, output_format="json" if output_format == "json" else "table")


def codex_install_skill_command(
    user: Annotated[
        bool,
        typer.Option("--user", help="Install into the current user's Skill directory."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show the installation plan without writing."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Install the repository qbank Skill for the current user."""
    try:
        context = discover_context()
        destination = user_skill_destination()
        scope = "explicit user scope" if user else "default user scope"
        typer.echo(f"Plan ({scope}): copy {context.root / '.agents/skills/qbank'}")
        typer.echo(f"Destination: {destination}")
        planned = install_repository_skill(context, dry_run=True)
        if dry_run:
            typer.echo(f"Dry-run: {planned.files} files would be installed.")
            return
        if not yes and not typer.confirm("Install this Skill for the current user?"):
            raise typer.Exit(code=int(ExitCode.GENERAL))
        result = install_repository_skill(context, dry_run=False)
        typer.echo(f"{result.action}: {result.destination} ({result.files} files)")
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc)
