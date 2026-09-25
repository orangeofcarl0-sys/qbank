"""Validated whole-batch question ingest."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from qbank.application.exchange import JsonLineRecord
from qbank.application.revision import repository_revision
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord, QuestionRecord, RepositorySnapshot
from qbank.errors import DataValidationError, QuestionNotFoundError
from qbank.models import (
    Diagnostic,
    DiagnosticCode,
    IngestItemResult,
    IngestOptions,
    IngestResult,
    ProjectConfig,
    Question,
)
from qbank.operations.common import (
    MutationServices,
    aggregate_hash,
    default_mutation_services,
    ensure_sources_are_consistent,
    question_diagnostics,
    require_repository_revision,
    sync_index_after_commit,
    write_history_record,
    write_lock,
)
from qbank.storage import prepare_question_for_write, render_question
from qbank.transaction import MutationTransaction


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
    repository_revision: str | None


def ingest_questions_in_context(
    context: ProjectContext,
    questions: Sequence[Question] = (),
    *,
    services: MutationServices | None = None,
    records: Sequence[JsonLineRecord] | None = None,
    options: IngestOptions | None = None,
    _verified_revision: str | None = None,
    **legacy_options: object,
) -> IngestResult:
    """Validate an entire batch, then commit valid records atomically."""
    options = _ingest_options(options, legacy_options)
    services = services or default_mutation_services(context)
    repository = services.repository
    expected_revision = (
        None if _verified_revision is not None or options.dry_run else repository_revision(context)
    )
    snapshot = repository.scan()
    ensure_sources_are_consistent(snapshot)
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
        repository_revision=expected_revision,
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
        semantic_errors, warnings = question_diagnostics(
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
    with write_lock(planning.context, planning.services).hold(planning.options.command):
        require_repository_revision(planning.context, planning.repository_revision)
        transaction = MutationTransaction.for_context(planning.context)
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
            write_history_record(
                transaction,
                planning.services.history,
                HistoryRecord(
                    operation="ingest",
                    question_ids=tuple(ids),
                    command=planning.options.command,
                    dry_run=False,
                    before_hash=aggregate_hash(before),
                    after_hash=aggregate_hash(after),
                    changes=tuple(sorted(changes, key=lambda item: item["id"])),
                ),
            )
            transaction.commit()
            index_updated, index_warnings = sync_index_after_commit(
                planning.context,
                planning.services.index,
                snapshot=planning.snapshot,
                questions=prepared_questions,
            )
            result.index_updated = index_updated
            result.warnings.extend(index_warnings)
        result.written = len(prepared_questions)
