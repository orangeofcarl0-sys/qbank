"""Question read, mutation, validation, and index CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.table import Table

from qbank.application import load_json_records, parse_json_lines
from qbank.bootstrap import create_project_services, create_question_service
from qbank.cli_support import (
    abort,
    discover_context,
    emit_json,
    emit_warnings,
    print_rows,
    question_rows,
    read_stdin,
    read_utf8,
    resolve_project_path,
    stdout_console,
)
from qbank.context import ProjectContext
from qbank.errors import DataValidationError, ExitCode, pydantic_error_text
from qbank.models import IngestOptions, QueryFilters, Question, QuestionPatch
from qbank.operations import (
    add_question_in_context,
    apply_patch_in_context,
    delete_question_in_context,
    ingest_questions_in_context,
)


def add_command(
    file: Annotated[
        Path | None,
        typer.Argument(help="JSON file; omit with --stdin."),
    ] = None,
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read JSON from standard input."),
    ] = False,
    upsert: Annotated[bool, typer.Option("--upsert")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Add one complete AI exchange JSON object."""
    try:
        context = discover_context()
        if stdin == (file is not None):
            raise DataValidationError("provide exactly one of a JSON file or --stdin")
        if stdin:
            text = read_stdin()
        else:
            if file is None:
                raise DataValidationError("missing JSON input file")
            text = read_utf8(resolve_project_path(context, file), label="question JSON")
        questions = load_json_records(text, jsonl=False)
        if len(questions) != 1:
            raise DataValidationError("qbank add accepts exactly one question")
        result = add_question_in_context(
            context,
            questions[0],
            services=create_project_services(context).mutations,
            upsert=upsert,
            dry_run=dry_run,
            command="qbank add",
        )
        emit_warnings(result, output_format)
        if output_format == "json":
            emit_json(result)
        else:
            typer.echo(f"{result.action}: {result.id} ({'dry-run' if dry_run else 'written'})")
    except Exception as exc:
        abort(exc, output_format=output_format)


def ingest_command(
    file: Annotated[Path, typer.Argument(help="JSONL input file.")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    upsert: Annotated[bool, typer.Option("--upsert")] = False,
    continue_on_error: Annotated[bool, typer.Option("--continue-on-error")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Validate then batch-import one JSON object per line."""
    try:
        context = discover_context()
        input_path = resolve_project_path(context, file)
        records = parse_json_lines(read_utf8(input_path, label="JSONL"))
        result = ingest_questions_in_context(
            context,
            services=create_project_services(context).mutations,
            records=records,
            options=IngestOptions(
                upsert=upsert,
                dry_run=dry_run,
                continue_on_error=continue_on_error,
                command=f"qbank ingest {file}",
            ),
        )
        emit_warnings(result, output_format)
        if output_format == "json":
            emit_json(result)
        else:
            typer.echo(
                f"Validated {result.total}; written {result.written}"
                + (" (dry-run)" if dry_run else "")
            )
            for item in result.results:
                if not item.ok:
                    typer.echo(
                        f"{item.id}: {item.errors}",
                        err=True,
                    )
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.VALIDATION))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def validate_command(
    question_id: Annotated[str | None, typer.Argument()] = None,
    changed: Annotated[bool, typer.Option("--changed")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Validate one question, changed questions, or the whole bank."""
    try:
        context = discover_context()
        report = create_question_service(context).validate_repository(
            question_id=question_id,
            changed=changed,
        )
        if output_format == "json":
            emit_json(report)
        elif output_format == "table":
            table = Table("Severity", "ID", "Code", "Message")
            for item in report.issues:
                table.add_row(
                    item.severity,
                    item.id or "",
                    item.code,
                    item.message,
                )
            stdout_console.print(table)
            typer.echo(
                f"{report.summary.questions} questions, "
                f"{report.summary.errors} errors, "
                f"{report.summary.warnings} warnings"
            )
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
        if not report.ok:
            raise typer.Exit(code=int(ExitCode.VALIDATION))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def questions_for_filters(
    filters: QueryFilters,
    context: ProjectContext | None = None,
) -> list[Question]:
    """Run one validated query within an optional existing context."""
    context = context or discover_context()
    return create_question_service(context).query_questions(filters)


def _filters(**values: Any) -> QueryFilters:
    try:
        return QueryFilters.model_validate(values)
    except ValidationError as exc:
        raise DataValidationError(f"invalid_filter: {pydantic_error_text(exc)}") from exc


def list_command(
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """List question summaries."""
    try:
        questions = questions_for_filters(_filters(limit=limit))
        print_rows(question_rows(questions), output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def get_command(
    question_ids: Annotated[
        list[str],
        typer.Argument(help="One or more question IDs."),
    ],
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Read complete question objects by ID."""
    try:
        context = discover_context()
        questions = create_question_service(context).get_questions(question_ids)
        if output_format == "json":
            data: Any = (
                questions[0].model_dump(mode="json", exclude_none=True)
                if len(questions) == 1
                else [question.model_dump(mode="json", exclude_none=True) for question in questions]
            )
            emit_json(data)
        elif output_format == "jsonl":
            for question in questions:
                typer.echo(
                    json.dumps(
                        question.model_dump(mode="json", exclude_none=True),
                        ensure_ascii=False,
                    )
                )
        elif output_format == "table":
            print_rows(question_rows(questions), "table")
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)


def query_command(
    subject: Annotated[str | None, typer.Option("--subject")] = None,
    chapter: Annotated[str | None, typer.Option("--chapter")] = None,
    topic: Annotated[list[str] | None, typer.Option("--topic")] = None,
    topic_mode: Annotated[str, typer.Option("--topic-mode")] = "and",
    question_type: Annotated[str | None, typer.Option("--type")] = None,
    status_value: Annotated[str | None, typer.Option("--status")] = None,
    difficulty_min: Annotated[
        int | None,
        typer.Option("--difficulty-min", min=1, max=5),
    ] = None,
    difficulty_max: Annotated[
        int | None,
        typer.Option("--difficulty-max", min=1, max=5),
    ] = None,
    language: Annotated[str | None, typer.Option("--language")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    fields: Annotated[str | None, typer.Option("--fields")] = None,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Filter questions by metadata and topic membership."""
    try:
        questions = questions_for_filters(
            _filters(
                subject=subject,
                chapter=chapter,
                topics=topic or [],
                topic_mode=topic_mode,
                question_type=question_type,
                status=status_value,
                difficulty_min=difficulty_min,
                difficulty_max=difficulty_max,
                language=language,
                limit=limit,
                offset=offset,
            )
        )
        selected = [item.strip() for item in fields.split(",")] if fields else None
        print_rows(
            question_rows(questions, selected),
            output_format,
        )
    except Exception as exc:
        abort(exc, output_format=output_format)


def search_command(
    text: Annotated[
        str,
        typer.Argument(help="Full-text search expression."),
    ],
    limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Search title, stem, answer, solution, topics, and chapter."""
    try:
        context = discover_context()
        rows = create_question_service(context).search_questions(text, limit=limit)
        print_rows(rows, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def patch_command(
    question_id: Annotated[str, typer.Argument()],
    stdin: Annotated[bool, typer.Option("--stdin")] = False,
    file: Annotated[Path | None, typer.Option("--file")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "json",
) -> None:
    """Apply a structured JSON patch to one question."""
    try:
        context = discover_context()
        if stdin == (file is not None):
            raise DataValidationError("provide exactly one of --stdin or --file")
        if stdin:
            text = read_stdin()
        else:
            if file is None:
                raise DataValidationError("missing patch input file")
            text = read_utf8(resolve_project_path(context, file), label="patch JSON")
        patch = QuestionPatch.model_validate_json(text)
        result = apply_patch_in_context(
            context,
            question_id,
            patch,
            services=create_project_services(context).mutations,
            dry_run=dry_run,
            command=f"qbank patch {question_id}",
        )
        emit_warnings(result, output_format)
        if output_format == "json":
            emit_json(result)
        else:
            typer.echo(f"{question_id}: {len(result.changes)} changes")
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.VALIDATION))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def delete_command(
    question_id: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Delete a question source file while retaining assets."""
    try:
        context = discover_context()
        if not dry_run and not yes and not typer.confirm(f"Delete {question_id}?"):
            raise typer.Abort()
        result = delete_question_in_context(
            context,
            question_id,
            services=create_project_services(context).mutations,
            dry_run=dry_run,
            command=f"qbank delete {question_id}",
        )
        emit_warnings(result, output_format)
        if output_format == "json":
            emit_json(result)
        else:
            action = "Would delete" if dry_run else "Deleted"
            typer.echo(f"{action} {question_id}")
    except typer.Abort:
        raise typer.Exit(code=int(ExitCode.GENERAL)) from None
    except Exception as exc:
        abort(exc, output_format=output_format)


def index_rebuild_command(
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Rebuild the SQLite FTS5 index from Markdown."""
    try:
        context = discover_context()
        count = create_question_service(context).rebuild_index()
        result = {"ok": True, "indexed": count}
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            typer.echo(f"Indexed {count} questions.")
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)
