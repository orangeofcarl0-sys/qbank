"""Tag taxonomy, statistics, and saved-view CLI adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import typer

from qbank.application import SavedViewService, TagApplicationService
from qbank.bootstrap import ProjectServices, create_project_services
from qbank.cli_support import (
    abort,
    discover_context,
    emit_json,
    emit_warnings,
    print_rows,
    question_rows,
)
from qbank.models import QueryFilters, SavedViewMutationResult, TagMutationResult


def _services() -> ProjectServices:
    return create_project_services(discover_context())


def tag_list_command(
    search: Annotated[str, typer.Option("--search")] = "",
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """List registered and unregistered tags with authoritative usage counts."""
    try:
        rows = _services().tags.suggestions(search, limit=limit)
        print_rows(rows, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def tag_show_command(
    tag: Annotated[str, typer.Argument()],
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Show one tag resolved from its slug, display name, or alias."""
    try:
        row = _services().tags.show_tag(tag)
        if output_format == "json":
            emit_json(row)
        else:
            print_rows([row], output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def tag_rename_command(
    old: Annotated[str, typer.Argument()],
    new: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Atomically rename a tag in taxonomy and question Markdown."""
    _emit_tag_mutation(
        lambda service: service.rename(
            old,
            new,
            dry_run=dry_run,
            command=f"qbank tag rename {old} {new}",
        ),
        output_format,
    )


def tag_merge_command(
    source: Annotated[str, typer.Argument()],
    target: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Atomically merge a source tag into a canonical target."""
    _emit_tag_mutation(
        lambda service: service.merge(
            source,
            target,
            dry_run=dry_run,
            command=f"qbank tag merge {source} {target}",
        ),
        output_format,
    )


def tag_delete_command(
    tag: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Atomically remove a tag from taxonomy and affected questions."""
    _emit_tag_mutation(
        lambda service: service.delete(
            tag,
            dry_run=dry_run,
            command=f"qbank tag delete {tag}",
        ),
        output_format,
    )


def tag_normalize_command(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Canonicalize aliases and register unknown topics as pending."""
    _emit_tag_mutation(
        lambda service: service.normalize(
            dry_run=dry_run,
            command="qbank tag normalize",
        ),
        output_format,
    )


def tag_stats_command(
    limit: Annotated[int, typer.Option("--limit", min=1)] = 100,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Show tag frequencies from authoritative Markdown."""
    try:
        rows = sorted(_services().tags.list_tags(), key=lambda item: (-item.count, item.slug))
        print_rows(rows[:limit], output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def tag_cooccur_command(
    top_n: Annotated[int, typer.Option("--top-n", min=1)] = 20,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Count co-occurring pairs among the Top-N tags."""
    try:
        print_rows(_services().tags.cooccurrence(top_n=top_n), output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def _emit_tag_mutation(
    callback: Callable[[TagApplicationService], TagMutationResult], output_format: str
) -> None:
    try:
        result = callback(_services().tags)
        emit_warnings(result, output_format)
        if output_format == "json":
            emit_json(result)
        else:
            mode = "Would affect" if result.dry_run else "Affected"
            typer.echo(f"{mode} {result.affected_questions} questions ({result.operation}).")
    except Exception as exc:
        abort(exc, output_format=output_format)


def view_list_command(
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """List fixed and user-created query views."""
    try:
        print_rows(_services().views.list_views(), output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def view_save_command(
    name: Annotated[str, typer.Argument()],
    text: Annotated[str | None, typer.Option("--search")] = None,
    subject: Annotated[str | None, typer.Option("--subject")] = None,
    chapter: Annotated[str | None, typer.Option("--chapter")] = None,
    topic: Annotated[list[str] | None, typer.Option("--topic")] = None,
    exclude_topic: Annotated[list[str] | None, typer.Option("--exclude-topic")] = None,
    topic_mode: Annotated[str, typer.Option("--topic-mode")] = "and",
    question_type: Annotated[str | None, typer.Option("--type")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    difficulty_min: Annotated[int | None, typer.Option("--difficulty-min")] = None,
    difficulty_max: Annotated[int | None, typer.Option("--difficulty-max")] = None,
    language: Annotated[str | None, typer.Option("--language")] = None,
    year: Annotated[int | None, typer.Option("--year")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Save the supplied combination of metadata and tag filters."""
    try:
        filters = QueryFilters.model_validate(
            {
                "text": text,
                "subject": subject,
                "chapter": chapter,
                "topics": topic or [],
                "excluded_topics": exclude_topic or [],
                "topic_mode": topic_mode,
                "question_type": question_type,
                "status": status,
                "difficulty_min": difficulty_min,
                "difficulty_max": difficulty_max,
                "language": language,
                "year": year,
            }
        )
        result = _services().views.save(name, filters, dry_run=dry_run)
        if output_format == "json":
            emit_json(result)
        else:
            typer.echo(f"{'Would save' if dry_run else 'Saved'} view {result.view.name}.")
    except Exception as exc:
        abort(exc, output_format=output_format)


def view_apply_command(
    name: Annotated[str, typer.Argument()],
    fields: Annotated[str | None, typer.Option("--fields")] = None,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Apply one named view to authoritative questions."""
    try:
        selected = [item.strip() for item in fields.split(",")] if fields else None
        questions = _services().views.apply(name)
        print_rows(question_rows(questions, selected), output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def view_rename_command(
    old: Annotated[str, typer.Argument()],
    new: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Rename a user-created saved view."""
    _emit_view_mutation(lambda service: service.rename(old, new, dry_run=dry_run), output_format)


def view_delete_command(
    name: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Delete a user-created saved view."""
    _emit_view_mutation(lambda service: service.delete(name, dry_run=dry_run), output_format)


def _emit_view_mutation(
    callback: Callable[[SavedViewService], SavedViewMutationResult], output_format: str
) -> None:
    try:
        result = callback(_services().views)
        if output_format == "json":
            emit_json(result)
        else:
            typer.echo(
                f"{'Would change' if result.dry_run else 'Changed'} view {result.view.name}."
            )
    except Exception as exc:
        abort(exc, output_format=output_format)
