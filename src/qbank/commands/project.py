"""Project lifecycle and diagnostic CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer
from rich.table import Table

from qbank.bootstrap import create_project_services
from qbank.cli_support import (
    abort,
    discover_context,
    emit_json,
    stdout_console,
)
from qbank.diagnostics import doctor_in_context, project_status_in_context
from qbank.errors import DataValidationError, ExitCode
from qbank.project import initialize_project
from qbank.schemas import SchemaKind, schema_for


def init_command(
    directory: Annotated[Path, typer.Argument(help="Target directory.")] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", help="Replace generated project files."),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: table or json."),
    ] = "table",
) -> None:
    """Initialize a qbank project in the current or named directory."""
    try:
        target = initialize_project(
            (Path.cwd() / directory).resolve(),
            force=force,
        )
        result = {"ok": True, "root": str(target)}
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            typer.echo(f"Initialized qbank project at {target}")
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)


def status_command(
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Summarize question counts and index state."""
    try:
        context = discover_context()
        result = project_status_in_context(
            context,
            create_project_services(context).diagnostics,
        )
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            typer.echo(f"Root: {result.root}")
            typer.echo(f"Questions: {result.questions} (invalid: {result.invalid})")
            typer.echo(f"By status: {result.by_status}")
            typer.echo(f"By subject: {result.by_subject}")
            typer.echo(f"By type: {result.by_type}")
            typer.echo(f"Index updated: {result.index_updated_at or 'never'}")
            typer.echo(f"Validation errors: {result.validation_errors}")
            typer.echo(f"Index dirty: {result.index_dirty}")
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)


def doctor_command(
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Check Python, project files, FTS5, Pandoc, schemas, and assets."""
    try:
        context = discover_context()
        result = doctor_in_context(
            context,
            create_project_services(context).diagnostics,
        )
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            table = Table("Status", "Check", "Details")
            for check in result.checks:
                table.add_row(
                    check.status,
                    check.name,
                    check.message,
                )
            stdout_console.print(table)
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.GENERAL))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def schema_command(
    kind: Annotated[
        str,
        typer.Option("--kind", help="question, paper, patch, asset, or asset-package."),
    ] = "question",
    output_format: Annotated[str, typer.Option("--format")] = "json",
) -> None:
    """Print a public question, paper, or patch JSON Schema."""
    try:
        if output_format != "json":
            raise DataValidationError("schema currently supports only --format json")
        if kind not in {"question", "paper", "patch", "asset", "asset-package"}:
            raise DataValidationError(
                "invalid_filter: --kind must be question, paper, patch, asset, or asset-package"
            )
        emit_json(schema_for(cast(SchemaKind, kind)))
    except Exception as exc:
        abort(exc, output_format=output_format)
