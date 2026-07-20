"""Preview, export, and paper CLI command adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from qbank.asset_server import create_asset_management_server
from qbank.bootstrap import create_project_services
from qbank.cli_support import (
    abort,
    discover_context,
    emit_json,
    emit_warnings,
    resolve_project_path,
)
from qbank.errors import DataValidationError, ExitCode
from qbank.exporters import export_questions_in_context
from qbank.models import PaperBuildOptions, PaperBuildRequest, QueryFilters
from qbank.papers import build_paper_in_context, load_paper, validate_paper_in_context
from qbank.preview import build_preview_in_context


def preview_command(
    serve: Annotated[
        bool,
        typer.Option(
            "--serve", help="Serve a localhost asset-management page after building preview."
        ),
    ] = False,
    port: Annotated[
        int, typer.Option("--port", help="Local port used with --serve (0 selects one). ")
    ] = 8765,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Build a searchable static preview under build/preview."""
    try:
        context = discover_context()
        services = create_project_services(context)
        result = build_preview_in_context(
            context,
            services.repository.scan(),
            services.renderer,
            services.assets,
        )
        if output_format not in {"json", "table"}:
            raise DataValidationError(f"unsupported output format: {output_format}")
        emit_warnings(result, output_format)
        if not serve:
            if output_format == "json":
                emit_json(result)
            else:
                typer.echo(f"Preview: {result.output} ({result.questions} questions)")
            return
        server, served = create_asset_management_server(
            context,
            services.assets,
            services.renderer,
            questions=result.questions,
            port=port,
        )
        if output_format == "json":
            emit_json(served)
        else:
            typer.echo(f"Preview: {result.output} ({result.questions} questions)")
            typer.echo(f"Asset management: {served.url} (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    except Exception as exc:
        abort(exc, output_format=output_format)


def export_command(
    subject: Annotated[str | None, typer.Option("--subject")] = None,
    chapter: Annotated[str | None, typer.Option("--chapter")] = None,
    topic: Annotated[list[str] | None, typer.Option("--topic")] = None,
    topic_mode: Annotated[str, typer.Option("--topic-mode")] = "and",
    question_type: Annotated[str | None, typer.Option("--type")] = None,
    status_value: Annotated[str | None, typer.Option("--status")] = None,
    difficulty_min: Annotated[int | None, typer.Option("--difficulty-min")] = None,
    difficulty_max: Annotated[int | None, typer.Option("--difficulty-max")] = None,
    language: Annotated[str | None, typer.Option("--language")] = None,
    output_format: Annotated[str, typer.Option("--format")] = "jsonl",
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Export filtered query results rather than a scored paper."""
    try:
        context = discover_context()
        services = create_project_services(context)
        filters = QueryFilters.model_validate(
            {
                "subject": subject,
                "chapter": chapter,
                "topics": topic or [],
                "topic_mode": topic_mode,
                "question_type": question_type,
                "status": status_value,
                "difficulty_min": difficulty_min,
                "difficulty_max": difficulty_max,
                "language": language,
                "limit": 1_000_000,
                "offset": 0,
            }
        )
        questions = services.questions.query_questions(filters)
        destination = (
            output if output is not None else context.paths.exports / f"questions.{output_format}"
        )
        result = export_questions_in_context(
            context,
            questions,
            output_format=output_format,
            output=destination,
            renderer=services.renderer,
            assets=services.assets,
        )
        emit_json(result)
    except Exception as exc:
        abort(exc, output_format="json")


def paper_validate_command(
    paper_file: Annotated[Path, typer.Argument()],
    allow_deprecated: Annotated[bool, typer.Option("--allow-deprecated")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Validate a paper file against the current question bank."""
    try:
        context = discover_context()
        services = create_project_services(context)
        paper = load_paper(resolve_project_path(context, paper_file))
        result = validate_paper_in_context(
            context,
            paper,
            allow_deprecated=allow_deprecated,
            snapshot=services.repository.scan(),
            assets=services.assets,
        )
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            typer.echo(
                f"{result.summary.questions} questions, "
                f"{result.summary.total_score:g} points, "
                f"{result.summary.errors} errors"
            )
            for item in result.issues:
                typer.echo(
                    f"{item.severity}: {item.message}",
                    err=True,
                )
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.VALIDATION))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def paper_build_command(
    paper_file: Annotated[Path, typer.Argument()],
    output_format: Annotated[str, typer.Option("--format")] = "md",
    output: Annotated[Path | None, typer.Option("--output")] = None,
    with_answers: Annotated[
        bool | None,
        typer.Option("--with-answers/--without-answers"),
    ] = None,
    with_solutions: Annotated[
        bool | None,
        typer.Option("--with-solutions/--without-solutions"),
    ] = None,
    with_rubric: Annotated[
        bool | None,
        typer.Option("--with-rubric/--without-rubric"),
    ] = None,
    show_ids: Annotated[
        bool | None,
        typer.Option("--show-ids/--hide-ids"),
    ] = None,
    allow_deprecated: Annotated[bool, typer.Option("--allow-deprecated")] = False,
    result_format: Annotated[str, typer.Option("--result-format")] = "table",
) -> None:
    """Build a student or answer paper as Markdown, HTML, or DOCX."""
    try:
        context = discover_context()
        services = create_project_services(context)
        request = PaperBuildRequest.model_validate(
            {
                "output_format": output_format,
                "output": output,
                "options": PaperBuildOptions(
                    with_answers=with_answers,
                    with_solutions=with_solutions,
                    with_rubric=with_rubric,
                    show_ids=show_ids,
                    allow_deprecated=allow_deprecated,
                ),
            }
        )
        result = build_paper_in_context(
            context,
            resolve_project_path(context, paper_file),
            request,
            services.repository.scan(),
            services.renderer,
            services.assets,
        )
        if result_format == "json":
            emit_json(result)
        elif result_format == "table":
            emit_warnings(result, result_format)
            typer.echo(f"Built {result.format}: {result.output}")
        else:
            raise DataValidationError(f"unsupported output format: {result_format}")
    except Exception as exc:
        abort(exc, output_format=result_format)
