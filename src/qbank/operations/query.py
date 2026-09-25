"""Validated structured queries over authoritative questions."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from pydantic import ValidationError

from qbank.application.service import question_matches
from qbank.context import ProjectContext
from qbank.errors import DataValidationError, pydantic_error_text
from qbank.models import ProjectConfig, QueryFilters, Question
from qbank.operations.common import ensure_sources_are_consistent, repository_with_snapshot


def query_questions_in_context(
    context: ProjectContext,
    filters: QueryFilters | None = None,
    **legacy_filters: object,
) -> list[Question]:
    """Filter authoritative questions through one validated filter model."""
    filters = _query_filters(filters, legacy_filters)
    _, snapshot = repository_with_snapshot(context)
    ensure_sources_are_consistent(snapshot)
    matches = [
        record.question for record in snapshot.records if question_matches(record.question, filters)
    ]
    matches.sort(key=lambda item: item.id)
    return matches[filters.offset : filters.offset + filters.limit]


def query_questions(
    root: Path,
    config: ProjectConfig,
    filters: QueryFilters | None = None,
    **legacy_filters: object,
) -> list[Question]:
    """Compatibility adapter for the context-based query use case."""
    return query_questions_in_context(
        ProjectContext.from_config(root, config),
        filters,
        **legacy_filters,
    )


def _query_filters(
    filters: QueryFilters | None,
    legacy_filters: dict[str, object],
) -> QueryFilters:
    if filters is not None and legacy_filters:
        raise DataValidationError("invalid_filter: pass QueryFilters or keyword filters, not both")
    if filters is not None:
        return filters
    values = dict(legacy_filters)
    topics = values.get("topics", ())
    values["topics"] = (
        list(cast(list[object] | tuple[object, ...], topics))
        if isinstance(topics, list | tuple)
        else topics
    )
    try:
        return QueryFilters.model_validate(values)
    except ValidationError as exc:
        raise DataValidationError(f"invalid_filter: {pydantic_error_text(exc)}") from exc
