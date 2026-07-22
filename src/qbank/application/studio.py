"""Interactive question commands with explicit application-level boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from qbank.application.ports import StudioQuestionMutationPort
from qbank.models import PatchQuestionResult, QuestionPatch


@dataclass(frozen=True, slots=True)
class StudioQuestionService:
    """Validate and atomically save one Studio question document."""

    mutations: StudioQuestionMutationPort

    def save_question(
        self,
        question_id: str,
        patch: QuestionPatch,
        *,
        dry_run: bool,
        command: str = "qbank desktop save",
    ) -> PatchQuestionResult:
        return self.mutations.save_question(
            question_id,
            patch,
            dry_run=dry_run,
            command=command,
        )
