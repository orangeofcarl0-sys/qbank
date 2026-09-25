"""Structured question patch application."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from qbank.application.revision import repository_revision
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord
from qbank.errors import DataValidationError
from qbank.models import (
    FieldChange,
    PatchQuestionResult,
    ProjectConfig,
    Question,
    QuestionPatch,
)
from qbank.operations.common import (
    MutationServices,
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
from qbank.utils import sha256_text


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


def patched_question(previous: Question, patch: QuestionPatch) -> Question:
    values = previous.model_dump()
    values.update(patch.set)
    topics = [item for item in previous.topics if item not in patch.remove_topics]
    topics.extend(item for item in patch.add_topics if item not in topics)
    values["topics"] = topics
    try:
        return Question.model_validate(values)
    except ValidationError as exc:
        raise DataValidationError(str(exc)) from exc


def apply_patch_in_context(
    context: ProjectContext,
    question_id: str,
    patch: QuestionPatch,
    *,
    services: MutationServices | None = None,
    dry_run: bool = False,
    command: str = "qbank patch",
    _verified_revision: str | None = None,
) -> PatchQuestionResult:
    """Apply a validated structured patch as one authoritative transaction."""
    root, config = context.root, context.config
    services = services or default_mutation_services(context)
    repository = services.repository
    expected_revision = (
        None if _verified_revision is not None or dry_run else repository_revision(context)
    )
    snapshot = repository.scan()
    ensure_sources_are_consistent(snapshot)
    previous_record = snapshot.locate(question_id)
    path = previous_record.path
    previous = previous_record.question
    candidate = patched_question(previous, patch)
    errors, validation_warnings = question_diagnostics(
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
    with write_lock(context, services).hold(command):
        require_repository_revision(context, expected_revision)
        transaction = MutationTransaction.for_context(context)
        transaction.write(destination, rendered)
        if path != destination:
            transaction.delete(path)
        write_history_record(
            transaction,
            services.history,
            HistoryRecord(
                operation="patch",
                question_ids=(question_id,),
                command=command,
                dry_run=False,
                before_hash=sha256_text(before_text),
                after_hash=sha256_text(rendered),
                changes=tuple(
                    change.model_dump(mode="json", exclude_none=True) for change in changes
                ),
            ),
        )
        transaction.commit()
        index_updated, index_warnings = sync_index_after_commit(
            context,
            services.index,
            snapshot=snapshot,
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
