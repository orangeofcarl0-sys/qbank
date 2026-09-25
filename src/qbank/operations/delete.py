"""Transactional single-question deletion."""

from __future__ import annotations

from pathlib import Path

from qbank.application.revision import repository_revision
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord
from qbank.errors import ConflictError, QuestionNotFoundError
from qbank.models import DeleteQuestionResult, ProjectConfig
from qbank.operations.common import (
    MutationServices,
    default_mutation_services,
    ensure_sources_are_consistent,
    require_repository_revision,
    sync_index_after_commit,
    write_history_record,
    write_lock,
)
from qbank.transaction import MutationTransaction
from qbank.utils import sha256_text


def delete_question_in_context(
    context: ProjectContext,
    question_id: str,
    *,
    services: MutationServices | None = None,
    dry_run: bool = False,
    command: str = "qbank delete",
) -> DeleteQuestionResult:
    """Delete one source and write history in a rollback-capable transaction."""
    root = context.root
    services = services or default_mutation_services(context)
    repository = services.repository
    expected_revision = repository_revision(context) if not dry_run else None
    snapshot = repository.scan()
    matches = list(snapshot.source_paths_for_id(question_id))
    if not matches:
        raise QuestionNotFoundError(f"question not found: {question_id}")
    if len(matches) > 1:
        raise ConflictError(f"duplicate question ID: {question_id}")
    path = matches[0]
    ensure_sources_are_consistent(snapshot, ignored_paths={path})
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
    with write_lock(context, services).hold(command):
        require_repository_revision(context, expected_revision)
        transaction = MutationTransaction.for_context(context)
        transaction.delete(path)
        write_history_record(
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
        index_updated, index_warnings = sync_index_after_commit(
            context,
            services.index,
            snapshot=snapshot,
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
