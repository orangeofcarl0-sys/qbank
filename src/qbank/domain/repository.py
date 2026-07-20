"""Domain representation of one deterministic repository scan."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qbank.errors import (
    ConflictError,
    DataValidationError,
    MarkdownParseError,
    QuestionNotFoundError,
)
from qbank.models import Question


@dataclass(frozen=True, slots=True)
class QuestionRecord:
    """One successfully parsed authoritative source."""

    path: Path
    relative_path: str
    text: str
    question: Question
    duplicate_sections: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class InvalidQuestionSource:
    """A malformed source retained in a repository snapshot."""

    path: Path
    relative_path: str
    error: str
    filename_id: str
    frontmatter_id: str | None

    def matches(self, question_id: str) -> bool:
        """Return whether best-effort identity points at *question_id*."""
        return self.filename_id == question_id or self.frontmatter_id == question_id


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """A deterministic, single-pass view of all authoritative sources."""

    records: tuple[QuestionRecord, ...]
    invalid_sources: tuple[InvalidQuestionSource, ...]
    duplicate_ids: frozenset[str]

    @property
    def paths(self) -> tuple[Path, ...]:
        """Return all source paths in deterministic order."""
        return tuple(
            sorted(
                (
                    *(record.path for record in self.records),
                    *(source.path for source in self.invalid_sources),
                ),
                key=str,
            )
        )

    def require_consistent(self, *, ignored_paths: set[Path] | None = None) -> None:
        """Reject malformed and duplicate authoritative sources."""
        ignored = {path.resolve() for path in ignored_paths or set()}
        invalid = [
            source for source in self.invalid_sources if source.path.resolve() not in ignored
        ]
        if invalid:
            raise DataValidationError(
                "\n".join(f"{source.path}: {source.error}" for source in invalid)
            )
        records = [record for record in self.records if record.path.resolve() not in ignored]
        duplicates = sorted(
            question_id
            for question_id, count in Counter(record.question.id for record in records).items()
            if count > 1
        )
        if duplicates:
            raise ConflictError(f"duplicate question ID(s): {', '.join(duplicates)}")

    def locate(self, question_id: str) -> QuestionRecord:
        """Locate one ID while surfacing malformed or occupied matching files."""
        invalid = [source for source in self.invalid_sources if source.matches(question_id)]
        if invalid:
            details = ", ".join(source.relative_path for source in invalid)
            raise MarkdownParseError(
                f"invalid source file for {question_id}: {details}: {invalid[0].error}"
            )
        occupied = [
            record
            for record in self.records
            if record.path.stem == question_id and record.question.id != question_id
        ]
        if occupied:
            record = occupied[0]
            raise ConflictError(
                f"source filename {record.relative_path} is occupied "
                f"by question ID {record.question.id}"
            )
        matches = [record for record in self.records if record.question.id == question_id]
        if not matches:
            raise QuestionNotFoundError(f"question not found: {question_id}")
        if len(matches) > 1:
            raise ConflictError(f"duplicate question ID: {question_id}")
        return matches[0]

    def source_paths_for_id(self, question_id: str) -> tuple[Path, ...]:
        """Return valid and malformed sources matching an identity hint."""
        matches = {
            record.path
            for record in self.records
            if record.question.id == question_id or record.path.stem == question_id
        }
        matches.update(
            source.path for source in self.invalid_sources if source.matches(question_id)
        )
        return tuple(sorted(matches, key=str))
