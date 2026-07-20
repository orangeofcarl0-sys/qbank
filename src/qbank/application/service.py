"""Reusable Python API for question read, validation, and search use cases."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from qbank.application.ports import (
    QuestionIndexPort,
    QuestionRepositoryPort,
    RepositoryValidatorPort,
)
from qbank.models import QueryFilters, Question, SearchHit, ValidationReport


@dataclass(frozen=True, slots=True)
class QuestionService:
    """Application service wired to repository, validator, and index ports."""

    repository: QuestionRepositoryPort
    validator: RepositoryValidatorPort
    index: QuestionIndexPort

    def query_questions(self, filters: QueryFilters | None = None) -> list[Question]:
        """Return deterministically filtered authoritative questions."""
        active_filters = filters or QueryFilters()
        snapshot = self.repository.scan()
        snapshot.require_consistent()
        matches = [
            record.question
            for record in snapshot.records
            if question_matches(record.question, active_filters)
        ]
        matches.sort(key=lambda question: question.id)
        return matches[active_filters.offset : active_filters.offset + active_filters.limit]

    def get_question(self, question_id: str) -> Question:
        """Return one question or raise its stable repository error."""
        return self.repository.scan().locate(question_id).question

    def get_questions(self, question_ids: Iterable[str]) -> list[Question]:
        """Return several questions from one shared repository snapshot."""
        snapshot = self.repository.scan()
        return [snapshot.locate(question_id).question for question_id in question_ids]

    def validate_repository(
        self,
        *,
        question_id: str | None = None,
        changed: bool = False,
    ) -> ValidationReport:
        """Validate through the injected validator without presentation output."""
        snapshot = None if changed else self.repository.scan()
        return self.validator.validate(
            question_id=question_id,
            changed=changed,
            snapshot=snapshot,
        )

    def search_questions(self, text: str, *, limit: int = 20) -> list[SearchHit]:
        """Search through the injected projection without knowing its backend."""
        snapshot = self.repository.scan()
        snapshot.require_consistent()
        self.index.ensure_searchable(snapshot)
        return self.index.search(text, limit=limit)

    def rebuild_index(self) -> int:
        """Rebuild the projection from one consistent repository snapshot."""
        snapshot = self.repository.scan()
        snapshot.require_consistent()
        return self.index.rebuild(snapshot)


def question_matches(question: Question, filters: QueryFilters) -> bool:
    """Return whether one question satisfies validated query filters."""
    metadata_matches = (
        (filters.subject is None or question.subject == filters.subject)
        and (filters.chapter is None or question.chapter == filters.chapter)
        and (filters.question_type is None or question.type == filters.question_type)
        and (filters.status is None or question.status == filters.status)
        and (filters.difficulty_min is None or question.difficulty >= filters.difficulty_min)
        and (filters.difficulty_max is None or question.difficulty <= filters.difficulty_max)
        and (filters.language is None or question.language == filters.language)
    )
    desired = set(filters.topics)
    available = set(question.topics)
    topics_match = (
        not desired
        or (filters.topic_mode == "and" and desired <= available)
        or (filters.topic_mode == "or" and bool(desired & available))
    )
    return metadata_matches and topics_match
