"""Shared CLI context, output, and error-boundary helpers."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn, Protocol, cast

import typer
from pydantic import BaseModel, ValidationError
from rich.console import Console
from rich.table import Table

from qbank.context import ProjectContext
from qbank.errors import DataValidationError, ExitCode, QBankError
from qbank.models import Diagnostic, DiagnosticCode, Question
from qbank.utils import json_text

stdout_console = Console()


class HasWarnings(Protocol):
    """Application result exposing normalized warnings."""

    @property
    def warnings(self) -> list[Diagnostic]: ...


def emit_json(data: Any) -> None:
    """Write one machine-readable JSON document to stdout."""
    typer.echo(json_text(data))


def require_output_format(value: str, *allowed: str) -> str:
    """Reject unsupported output formats before a command performs any work."""
    if value not in allowed:
        expected = ", ".join(allowed)
        raise DataValidationError(
            f"unsupported output format: {value}; expected one of: {expected}"
        )
    return value


def abort(exc: Exception, *, output_format: str = "table") -> NoReturn:
    """Map an exception to stable CLI output and an exit code."""
    if isinstance(exc, QBankError):
        code = int(exc.exit_code)
        diagnostic_code = _error_code(exc)
    elif isinstance(exc, ValidationError | json.JSONDecodeError):
        code = int(ExitCode.VALIDATION)
        diagnostic_code = (
            DiagnosticCode.MODEL_VALIDATION
            if isinstance(exc, ValidationError)
            else DiagnosticCode.INVALID_JSON
        )
    else:
        code = int(ExitCode.GENERAL)
        diagnostic_code = DiagnosticCode.GENERAL_ERROR
    if output_format == "json":
        payload: dict[str, Any] = {
            "ok": False,
            "code": diagnostic_code,
            "error": str(exc),
            "exit_code": code,
        }
        if isinstance(exc, QBankError) and exc.details:
            payload["details"] = exc.details
        emit_json(payload)
    else:
        typer.echo(f"Error: {exc}", err=True)
    raise typer.Exit(code=code)


def _error_code(exc: QBankError) -> DiagnosticCode:
    prefix = str(exc).partition(":")[0]
    try:
        return DiagnosticCode(prefix)
    except ValueError:
        return exc.code


def emit_warnings(result: HasWarnings, output_format: str) -> None:
    """Keep human warnings on stderr and machine JSON on stdout."""
    if output_format == "json":
        return
    for warning in result.warnings:
        typer.echo(f"Warning [{warning.code}]: {warning.message}", err=True)


def discover_context() -> ProjectContext:
    """Discover and validate the current project exactly once."""
    return ProjectContext.discover()


def read_stdin() -> str:
    """Read redirected stdin as UTF-8, including PowerShell pipelines."""
    binary = getattr(sys.stdin, "buffer", None)
    if binary is None:
        return sys.stdin.read()
    raw = binary.read()
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    encoding = sys.stdin.encoding or "utf-8"
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise DataValidationError("stdin must be UTF-8 or UTF-16 text") from exc


def read_utf8(path: Path, *, label: str = "input") -> str:
    """Read one UTF-8 input and normalize decoding failures as validation errors."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise DataValidationError(f"{label} must be valid UTF-8: {path}") from exc


def resolve_project_path(context: ProjectContext, value: Path) -> Path:
    """Resolve explicit input paths with current-directory precedence."""
    if value.is_absolute():
        return value
    cwd_candidate = (Path.cwd() / value).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (context.root / value).resolve()


def question_rows(
    questions: Sequence[Question],
    fields: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Select stable fields from complete question objects."""
    selected = (
        list(fields)
        if fields
        else [
            "id",
            "title",
            "type",
            "subject",
            "difficulty",
            "status",
            "topics",
        ]
    )
    unknown = [field for field in selected if field not in Question.model_fields]
    if unknown:
        raise DataValidationError(f"unknown fields: {', '.join(unknown)}")
    return [
        {
            field: question.model_dump(mode="json", exclude_none=True).get(field)
            for field in selected
        }
        for question in questions
    ]


def print_rows(
    rows: Sequence[dict[str, Any] | BaseModel],
    output_format: str,
) -> None:
    """Render tabular or machine-readable row collections."""
    normalized = [
        row.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(row, BaseModel)
        else row
        for row in rows
    ]
    if output_format == "json":
        emit_json(normalized)
        return
    if output_format == "jsonl":
        for row in normalized:
            typer.echo(json.dumps(row, ensure_ascii=False))
        return
    if output_format != "table":
        raise DataValidationError(f"unsupported output format: {output_format}")
    if not normalized:
        typer.echo("No questions.")
        return
    table = Table(show_header=True, header_style="bold")
    for key in normalized[0]:
        table.add_column(key)
    for row in normalized:
        table.add_row(*[_display_value(value) for value in row.values()])
    stdout_console.print(table)


def _display_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in cast(list[object], value))
    return "" if value is None else str(value)
