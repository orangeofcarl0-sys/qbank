"""Transactional single-question creation and replacement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from qbank.application.revision import repository_revision
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord, QuestionRecord
from qbank.errors import ConflictError, DataValidationError, QuestionNotFoundError
from qbank.models import AddQuestionResult, ProjectConfig, Question
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
from qbank.operations.patch import diff_questions
from qbank.storage import prepare_question_for_write, render_question
from qbank.transaction import MutationTransaction
from qbank.utils import sha256_text


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
    services = services or default_mutation_services(context)
    repository = services.repository
    expected_revision = repository_revision(context) if not dry_run else None
    snapshot = repository.scan()
    ensure_sources_are_consistent(snapshot)
    destination = repository.destination(question)
    errors, validation_warnings = question_diagnostics(
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
    action: Literal["create", "update"] = "update" if previous else "create"
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
    with write_lock(context, services).hold(command):
        require_repository_revision(context, expected_revision)
        transaction = MutationTransaction.for_context(context)
        transaction.write(destination, rendered)
        if previous_record is not None and previous_record.path != destination:
            transaction.delete(previous_record.path)
        write_history_record(
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
        index_updated, index_warnings = sync_index_after_commit(
            context,
            services.index,
            snapshot=snapshot,
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
