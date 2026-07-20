"""Validated, transactional question mutations and source queries."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from qbank.application.exchange import JsonLineRecord
from qbank.application.ports import (
    HistoryStorePort,
    MutableQuestionRepositoryPort,
    MutationIndexPort,
)
from qbank.application.service import question_matches
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord, QuestionRecord, RepositorySnapshot
from qbank.errors import (
    ConflictError,
    DataValidationError,
    QuestionNotFoundError,
    pydantic_error_text,
)
from qbank.history import JsonHistoryStore
from qbank.models import (
    AddQuestionResult,
    DeleteQuestionResult,
    Diagnostic,
    DiagnosticCode,
    FieldChange,
    IngestItemResult,
    IngestOptions,
    IngestResult,
    PatchQuestionResult,
    ProjectConfig,
    QueryFilters,
    Question,
    QuestionPatch,
)
from qbank.repository import MarkdownQuestionRepository
from qbank.search_index import SQLiteSearchIndex
from qbank.storage import prepare_question_for_write, render_question
from qbank.transaction import MutationTransaction
from qbank.utils import sha256_text
from qbank.validation import validate_question


def question_dict(question: Question) -> dict[str, Any]:
    """Return a JSON-ready full exchange object."""
    return question.model_dump(mode="json", exclude_none=True)


def _diagnostics(
    root: Path,
    config: ProjectConfig,
    question: Question,
    destination: Path,
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    issues = validate_question(root, config, destination, question)
    return (
        [item for item in issues if item.severity == "error"],
        [item for item in issues if item.severity == "warning"],
    )


def _ensure_sources_are_consistent(
    snapshot: RepositorySnapshot,
    *,
    ignored_paths: set[Path] | None = None,
) -> None:
    """Reject writes while any authoritative source is malformed or duplicated."""
    snapshot.require_consistent(ignored_paths=ignored_paths)


def _repository(
    context: ProjectContext,
) -> tuple[MarkdownQuestionRepository, RepositorySnapshot]:
    repository = MarkdownQuestionRepository(context)
    return repository, repository.scan()


@dataclass(frozen=True, slots=True)
class MutationServices:
    """Concrete-free dependencies for authoritative mutation use cases."""

    repository: MutableQuestionRepositoryPort
    index: MutationIndexPort
    history: HistoryStorePort


def _default_mutation_services(context: ProjectContext) -> MutationServices:
    """Compatibility wiring for callers that predate the composition root."""
    return MutationServices(
        repository=MarkdownQuestionRepository(context),
        index=SQLiteSearchIndex(context),
        history=JsonHistoryStore(context),
    )


@dataclass(frozen=True, slots=True)
class QuestionMutationPlan:
    """One validated source mutation within a batch."""

    line: int
    requested: Question
    prepared: Question
    destination: Path
    previous: QuestionRecord | None
    rendered: str
    warnings: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class IngestEntry:
    """One normalized batch entry before semantic planning."""

    line: int
    question: Question | None
    errors: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class IngestPlanningContext:
    """Shared state used while planning every batch entry."""

    context: ProjectContext
    services: MutationServices
    snapshot: RepositorySnapshot
    duplicate_ids: frozenset[str]
    options: IngestOptions


def _aggregate_hash(values: dict[str, str]) -> str | None:
    if not values:
        return None
    serialized = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(serialized)


def _sync_index(
    config: ProjectConfig,
    index: MutationIndexPort,
    *,
    questions: Sequence[Question] = (),
    deleted_ids: Sequence[str] = (),
) -> tuple[bool, list[Diagnostic]]:
    if not config.index.enabled:
        return False, []
    try:
        index.apply(
            questions=tuple(questions),
            deleted_ids=tuple(deleted_ids),
        )
    except Exception as exc:
        message = f"authoritative files committed, but the index update failed: {exc}"
        try:
            index.mark_dirty(message)
        except Exception as marker_exc:
            message += f"; dirty marker could not be written: {marker_exc}"
        return False, [
            Diagnostic(
                severity="warning",
                code=DiagnosticCode.INDEX_DIRTY,
                message=message,
            )
        ]
    return True, []


def _history_write(
    transaction: MutationTransaction,
    history: HistoryStorePort,
    record: HistoryRecord,
) -> None:
    path, text = history.prepare(record)
    transaction.write(path, text)


def add_question_in_context(
    context: ProjectContext,
    question: Question,
    *,
    services: MutationServices | None = None,
    upsert: bool = False,
    dry_run: bool = False,
    command: str = "qbank add",
) -> AddQuestionResult:
    """Validate and transactionally add or update one complete question."""
    root, config = context.root, context.config
    services = services or _default_mutation_services(context)
    repository = services.repository
    snapshot = repository.scan()
    _ensure_sources_are_consistent(snapshot)
    destination = repository.destination(question)
    errors, validation_warnings = _diagnostics(
        root,
        config,
        question,
        destination,
    )
    if errors:
        raise DataValidationError(
            json.dumps(
                [error.model_dump(mode="json", exclude_none=True) for error in errors],
                ensure_ascii=False,
            )
        )
    previous_record: QuestionRecord | None = None
    try:
        previous_record = snapshot.locate(question.id)
        if not upsert:
            raise ConflictError(f"question already exists: {question.id}")
    except QuestionNotFoundError:
        pass
    previous = previous_record.question if previous_record else None
    prepared = prepare_question_for_write(question, previous=previous)
    destination = repository.destination(prepared)
    rendered = render_question(prepared)
    action = "update" if previous else "create"
    changes = (
        [
            change.model_dump(mode="json", exclude_none=True)
            for change in diff_questions(previous, prepared)
        ]
        if previous
        else [{"field": "*", "new": "created"}]
    )
    result = AddQuestionResult(
        ok=True,
        dry_run=dry_run,
        id=prepared.id,
        action=action,
        path=destination.relative_to(root).as_posix(),
        validation_errors=[],
        validation_warnings=validation_warnings,
        warnings=list(validation_warnings),
        index_updated=False,
    )
    if dry_run:
        return result
    transaction = MutationTransaction()
    transaction.write(destination, rendered)
    if previous_record is not None and previous_record.path != destination:
        transaction.delete(previous_record.path)
    _history_write(
        transaction,
        services.history,
        HistoryRecord(
            operation="upsert" if previous else "add",
            question_ids=(prepared.id,),
            command=command,
            dry_run=False,
            before_hash=sha256_text(previous_record.text if previous_record else None),
            after_hash=sha256_text(rendered),
            changes=tuple(changes),
        ),
    )
    transaction.commit()
    index_updated, index_warnings = _sync_index(
        config,
        services.index,
        questions=[prepared],
    )
    result.index_updated = index_updated
    result.warnings.extend(index_warnings)
    return result


def add_question(
    root: Path,
    config: ProjectConfig,
    question: Question,
    *,
    upsert: bool = False,
    dry_run: bool = False,
    command: str = "qbank add",
) -> AddQuestionResult:
    """Compatibility adapter for the context-based add use case."""
    return add_question_in_context(
        ProjectContext.from_config(root, config),
        question,
        upsert=upsert,
        dry_run=dry_run,
        command=command,
    )


def ingest_questions_in_context(
    context: ProjectContext,
    questions: Sequence[Question] = (),
    *,
    services: MutationServices | None = None,
    records: Sequence[JsonLineRecord] | None = None,
    options: IngestOptions | None = None,
    **legacy_options: object,
) -> IngestResult:
    """Validate an entire batch, then commit valid records atomically."""
    options = _ingest_options(options, legacy_options)
    services = services or _default_mutation_services(context)
    repository = services.repository
    snapshot = repository.scan()
    _ensure_sources_are_consistent(snapshot)
    entries = _ingest_entries(questions, records)
    valid_questions = [
        entry.question for entry in entries if entry.question is not None and not entry.errors
    ]
    duplicate_ids = frozenset(
        question_id
        for question_id, count in Counter(item.id for item in valid_questions).items()
        if count > 1
    )
    planning = IngestPlanningContext(
        context=context,
        services=services,
        snapshot=snapshot,
        duplicate_ids=duplicate_ids,
        options=options,
    )
    planned = [_plan_ingest_entry(planning, entry) for entry in entries]
    results = [result for result, _ in planned]
    plans = [plan for _, plan in planned if plan is not None]
    has_errors = any(not item.ok for item in results)
    top_warnings = [warning for item in results for warning in item.warnings]
    result = IngestResult(
        ok=not has_errors or options.continue_on_error,
        dry_run=options.dry_run,
        written=0,
        total=len(entries),
        results=results,
        validation_warnings=list(top_warnings),
        warnings=list(top_warnings),
        index_updated=False,
    )
    if has_errors and not options.continue_on_error:
        return result
    if options.dry_run:
        result.would_write = len(plans)
        return result
    _commit_ingest(planning, plans, result)
    return result


def ingest_questions(
    root: Path,
    config: ProjectConfig,
    questions: Sequence[Question] = (),
    *,
    records: Sequence[JsonLineRecord] | None = None,
    options: IngestOptions | None = None,
    **legacy_options: object,
) -> IngestResult:
    """Compatibility adapter for the context-based ingest use case."""
    normalized_options = _ingest_options(options, legacy_options)
    return ingest_questions_in_context(
        ProjectContext.from_config(root, config),
        questions,
        records=records,
        options=normalized_options,
    )


def _ingest_options(
    options: IngestOptions | None,
    legacy_options: dict[str, object],
) -> IngestOptions:
    if options is not None and legacy_options:
        raise DataValidationError("pass IngestOptions or keyword options, not both")
    if options is not None:
        return options
    try:
        return IngestOptions.model_validate(legacy_options)
    except ValidationError as exc:
        raise DataValidationError(str(exc)) from exc


def _ingest_entries(
    questions: Sequence[Question],
    records: Sequence[JsonLineRecord] | None,
) -> list[IngestEntry]:
    if records is not None:
        return [
            IngestEntry(
                line=record.line,
                question=record.question,
                errors=tuple(record.errors),
            )
            for record in records
        ]
    return [
        IngestEntry(line=index, question=question, errors=())
        for index, question in enumerate(questions, start=1)
    ]


def _plan_ingest_entry(
    planning: IngestPlanningContext,
    entry: IngestEntry,
) -> tuple[IngestItemResult, QuestionMutationPlan | None]:
    errors = list(entry.errors)
    warnings: list[Diagnostic] = []
    previous: QuestionRecord | None = None
    if entry.question is not None:
        semantic_errors, warnings = _diagnostics(
            planning.context.root,
            planning.context.config,
            entry.question,
            planning.services.repository.destination(entry.question),
        )
        errors.extend(semantic_errors)
        errors.extend(_batch_identity_errors(planning, entry.question))
        try:
            previous = planning.snapshot.locate(entry.question.id)
        except QuestionNotFoundError:
            previous = None
        if previous is not None and not planning.options.upsert:
            errors.append(
                Diagnostic(
                    id=entry.question.id,
                    code=DiagnosticCode.CONFLICT,
                    message="question already exists; use --upsert",
                )
            )
    result = IngestItemResult(
        line=entry.line,
        id=entry.question.id if entry.question is not None else None,
        ok=not errors,
        action="update" if previous is not None else "create",
        errors=errors,
        warnings=warnings,
        skipped=bool(errors),
    )
    if entry.question is None or errors:
        return result, None
    prepared = prepare_question_for_write(
        entry.question,
        previous=previous.question if previous is not None else None,
    )
    plan = QuestionMutationPlan(
        line=entry.line,
        requested=entry.question,
        prepared=prepared,
        destination=planning.services.repository.destination(prepared),
        previous=previous,
        rendered=render_question(prepared),
        warnings=tuple(warnings),
    )
    return result, plan


def _batch_identity_errors(
    planning: IngestPlanningContext,
    question: Question,
) -> list[Diagnostic]:
    if question.id not in planning.duplicate_ids:
        return []
    return [
        Diagnostic(
            id=question.id,
            code=DiagnosticCode.DUPLICATE_BATCH_ID,
            message="ID occurs more than once in the input batch",
        )
    ]


def _commit_ingest(
    planning: IngestPlanningContext,
    plans: list[QuestionMutationPlan],
    result: IngestResult,
) -> None:
    transaction = MutationTransaction()
    before: dict[str, str] = {}
    after: dict[str, str] = {}
    changes: list[dict[str, Any]] = []
    prepared_questions: list[Question] = []
    for plan in plans:
        transaction.write(plan.destination, plan.rendered)
        if plan.previous is not None and plan.previous.path != plan.destination:
            transaction.delete(plan.previous.path)
        if plan.previous is not None:
            before[plan.prepared.id] = plan.previous.text
        after[plan.prepared.id] = plan.rendered
        prepared_questions.append(plan.prepared)
        changes.append(
            {
                "id": plan.prepared.id,
                "action": "update" if plan.previous else "create",
                "path": plan.destination.relative_to(planning.context.root).as_posix(),
            }
        )
    if prepared_questions:
        ids = sorted(question.id for question in prepared_questions)
        _history_write(
            transaction,
            planning.services.history,
            HistoryRecord(
                operation="ingest",
                question_ids=tuple(ids),
                command=planning.options.command,
                dry_run=False,
                before_hash=_aggregate_hash(before),
                after_hash=_aggregate_hash(after),
                changes=tuple(sorted(changes, key=lambda item: item["id"])),
            ),
        )
        transaction.commit()
        index_updated, index_warnings = _sync_index(
            planning.context.config,
            planning.services.index,
            questions=prepared_questions,
        )
        result.index_updated = index_updated
        result.warnings.extend(index_warnings)
    result.written = len(prepared_questions)


def diff_questions(
    previous: Question | None,
    current: Question,
) -> list[FieldChange]:
    """Return a stable field-level question diff."""
    old = previous.model_dump(mode="json") if previous else {}
    new = current.model_dump(mode="json")
    changes: list[FieldChange] = []
    for field in Question.model_fields:
        if old.get(field) != new.get(field):
            changes.append(
                FieldChange(
                    field=field,
                    old=old.get(field),
                    new=new.get(field),
                )
            )
    return changes


def apply_patch_in_context(
    context: ProjectContext,
    question_id: str,
    patch: QuestionPatch,
    *,
    services: MutationServices | None = None,
    dry_run: bool = False,
    command: str = "qbank patch",
) -> PatchQuestionResult:
    """Apply a validated structured patch as one authoritative transaction."""
    root, config = context.root, context.config
    services = services or _default_mutation_services(context)
    repository = services.repository
    snapshot = repository.scan()
    _ensure_sources_are_consistent(snapshot)
    previous_record = snapshot.locate(question_id)
    path = previous_record.path
    previous = previous_record.question
    values = previous.model_dump()
    values.update(patch.set)
    topics = [item for item in previous.topics if item not in patch.remove_topics]
    topics.extend(item for item in patch.add_topics if item not in topics)
    values["topics"] = topics
    try:
        candidate = Question.model_validate(values)
    except ValidationError as exc:
        raise DataValidationError(str(exc)) from exc
    errors, validation_warnings = _diagnostics(
        root,
        config,
        candidate,
        repository.destination(candidate),
    )
    if errors:
        return PatchQuestionResult(
            ok=False,
            id=question_id,
            dry_run=dry_run,
            changes=[],
            validation_errors=errors,
            validation_warnings=validation_warnings,
            warnings=validation_warnings,
            index_updated=False,
        )
    prepared = prepare_question_for_write(candidate, previous=previous)
    changes = [
        change for change in diff_questions(previous, prepared) if change.field != "updated_at"
    ]
    result = PatchQuestionResult(
        ok=True,
        id=question_id,
        dry_run=dry_run,
        changes=changes,
        validation_errors=[],
        validation_warnings=validation_warnings,
        warnings=list(validation_warnings),
        index_updated=False,
    )
    if dry_run:
        return result
    before_text = previous_record.text
    destination = repository.destination(prepared)
    rendered = render_question(prepared)
    transaction = MutationTransaction()
    transaction.write(destination, rendered)
    if path != destination:
        transaction.delete(path)
    _history_write(
        transaction,
        services.history,
        HistoryRecord(
            operation="patch",
            question_ids=(question_id,),
            command=command,
            dry_run=False,
            before_hash=sha256_text(before_text),
            after_hash=sha256_text(rendered),
            changes=tuple(change.model_dump(mode="json", exclude_none=True) for change in changes),
        ),
    )
    transaction.commit()
    index_updated, index_warnings = _sync_index(
        config,
        services.index,
        questions=[prepared],
    )
    result.index_updated = index_updated
    result.warnings.extend(index_warnings)
    return result


def apply_patch(
    root: Path,
    config: ProjectConfig,
    question_id: str,
    patch: QuestionPatch,
    *,
    dry_run: bool = False,
    command: str = "qbank patch",
) -> PatchQuestionResult:
    """Compatibility adapter for the context-based patch use case."""
    return apply_patch_in_context(
        ProjectContext.from_config(root, config),
        question_id,
        patch,
        dry_run=dry_run,
        command=command,
    )


def delete_question_in_context(
    context: ProjectContext,
    question_id: str,
    *,
    services: MutationServices | None = None,
    dry_run: bool = False,
    command: str = "qbank delete",
) -> DeleteQuestionResult:
    """Delete one source and write history in a rollback-capable transaction."""
    root, config = context.root, context.config
    services = services or _default_mutation_services(context)
    repository = services.repository
    snapshot = repository.scan()
    matches = list(snapshot.source_paths_for_id(question_id))
    if not matches:
        raise QuestionNotFoundError(f"question not found: {question_id}")
    if len(matches) > 1:
        raise ConflictError(f"duplicate question ID: {question_id}")
    path = matches[0]
    _ensure_sources_are_consistent(snapshot, ignored_paths={path})
    before_text = path.read_text(encoding="utf-8")
    result = DeleteQuestionResult(
        ok=True,
        dry_run=dry_run,
        id=question_id,
        path=path.relative_to(root).as_posix(),
        warnings=[],
        index_updated=False,
    )
    if dry_run:
        return result
    transaction = MutationTransaction()
    transaction.delete(path)
    _history_write(
        transaction,
        services.history,
        HistoryRecord(
            operation="delete",
            question_ids=(question_id,),
            command=command,
            dry_run=False,
            before_hash=sha256_text(before_text),
            after_hash=None,
            changes=(
                {
                    "field": "*",
                    "old": "present",
                    "new": "deleted",
                },
            ),
        ),
    )
    transaction.commit()
    index_updated, index_warnings = _sync_index(
        config,
        services.index,
        deleted_ids=[question_id],
    )
    result.index_updated = index_updated
    result.warnings.extend(index_warnings)
    return result


def delete_question(
    root: Path,
    config: ProjectConfig,
    question_id: str,
    *,
    dry_run: bool = False,
    command: str = "qbank delete",
) -> DeleteQuestionResult:
    """Compatibility adapter for the context-based delete use case."""
    return delete_question_in_context(
        ProjectContext.from_config(root, config),
        question_id,
        dry_run=dry_run,
        command=command,
    )


def query_questions_in_context(
    context: ProjectContext,
    filters: QueryFilters | None = None,
    **legacy_filters: object,
) -> list[Question]:
    """Filter authoritative questions through one validated filter model."""
    filters = _query_filters(filters, legacy_filters)
    _, snapshot = _repository(context)
    _ensure_sources_are_consistent(snapshot)
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
