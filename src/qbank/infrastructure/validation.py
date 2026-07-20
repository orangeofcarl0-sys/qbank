"""Validation adapter for the application service."""

from __future__ import annotations

from dataclasses import dataclass

from qbank.context import ProjectContext
from qbank.domain import RepositorySnapshot
from qbank.models import ValidationReport
from qbank.validation import validate_repository_in_context


@dataclass(frozen=True, slots=True)
class RepositoryValidationAdapter:
    """Bind repository validation to one immutable project context."""

    context: ProjectContext

    def validate(
        self,
        *,
        question_id: str | None = None,
        changed: bool = False,
        snapshot: RepositorySnapshot | None = None,
    ) -> ValidationReport:
        return validate_repository_in_context(
            self.context,
            question_id=question_id,
            changed=changed,
            snapshot=snapshot,
        )
