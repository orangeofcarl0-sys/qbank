"""Shared dependencies for validated, transactional question mutations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qbank.application.locking import RepositoryWriteLockPort
from qbank.application.ports import (
    HistoryStorePort,
    MutableQuestionRepositoryPort,
    MutationIndexPort,
)
from qbank.application.revision import (
    planned_question_projection_revision,
    question_projection_revision,
    repository_revision,
)
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord, RepositorySnapshot
from qbank.errors import RepositoryRevisionChangedError
from qbank.history import JsonHistoryStore
from qbank.models import Diagnostic, DiagnosticCode, ProjectConfig, Question
from qbank.repository import MarkdownQuestionRepository
from qbank.search_index import SQLiteSearchIndex
from qbank.transaction import MutationTransaction
from qbank.utils import sha256_text
from qbank.validation import validate_question


def question_dict(question: Question) -> dict[str, Any]:
    """Return a JSON-ready full exchange object."""
    return question.model_dump(mode="json", exclude_none=True)


def question_diagnostics(
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


def ensure_sources_are_consistent(
    snapshot: RepositorySnapshot,
    *,
    ignored_paths: set[Path] | None = None,
) -> None:
    """Reject writes while any authoritative source is malformed or duplicated."""
    snapshot.require_consistent(ignored_paths=ignored_paths)


def repository_with_snapshot(
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
    lock: RepositoryWriteLockPort | None = None


def default_mutation_services(context: ProjectContext) -> MutationServices:
    """Compatibility wiring for callers that predate the composition root."""
    from qbank.infrastructure.locking import RepositoryWriteLock

    return MutationServices(
        repository=MarkdownQuestionRepository(context),
        index=SQLiteSearchIndex(context),
        history=JsonHistoryStore(context),
        lock=RepositoryWriteLock(context),
    )


def write_lock(
    context: ProjectContext,
    services: MutationServices,
) -> RepositoryWriteLockPort:
    if services.lock is not None:
        return services.lock
    from qbank.infrastructure.locking import RepositoryWriteLock

    return RepositoryWriteLock(context)


def aggregate_hash(values: dict[str, str]) -> str | None:
    if not values:
        return None
    serialized = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(serialized)


def sync_index_after_commit(
    context: ProjectContext,
    index: MutationIndexPort,
    *,
    snapshot: RepositorySnapshot,
    questions: Sequence[Question] = (),
    deleted_ids: Sequence[str] = (),
) -> tuple[bool, list[Diagnostic]]:
    if not context.config.index.enabled:
        return False, []
    try:
        expected_projection = planned_question_projection_revision(
            context,
            snapshot,
            questions=questions,
            deleted_ids=deleted_ids,
        )
        if question_projection_revision(context) != expected_projection:
            raise RepositoryRevisionChangedError(
                "repository_revision_changed: question sources changed before index sync"
            )
        question_values = tuple(questions)
        deleted_values = tuple(deleted_ids)
        topic_values = topics_after(
            snapshot,
            questions=questions,
            deleted_ids=deleted_ids,
        )
        if isinstance(index, SQLiteSearchIndex):
            index.apply(
                questions=question_values,
                deleted_ids=deleted_values,
                topics_by_question=topic_values,
                source_revision=expected_projection,
            )
        else:
            index.apply(
                questions=question_values,
                deleted_ids=deleted_values,
                topics_by_question=topic_values,
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


def topics_after(
    snapshot: RepositorySnapshot,
    *,
    questions: Sequence[Question] = (),
    deleted_ids: Sequence[str] = (),
) -> Mapping[str, tuple[str, ...]]:
    """Project post-commit topic relations from the already scanned snapshot."""
    deleted = set(deleted_ids)
    topics = {
        record.question.id: tuple(record.question.topics)
        for record in snapshot.records
        if record.question.id not in deleted
    }
    topics.update({question.id: tuple(question.topics) for question in questions})
    return topics


def write_history_record(
    transaction: MutationTransaction,
    history: HistoryStorePort,
    record: HistoryRecord,
) -> None:
    path, text = history.prepare(record)
    transaction.write(path, text)


def require_repository_revision(context: ProjectContext, expected: str | None) -> None:
    if expected is None:
        return
    current = repository_revision(context)
    if current != expected:
        raise RepositoryRevisionChangedError(
            "repository_revision_changed: repository changed before the protected commit",
            details={"expected": expected, "current": current},
        )
