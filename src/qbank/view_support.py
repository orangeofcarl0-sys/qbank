"""Concrete project-derived membership for built-in saved views."""

from __future__ import annotations

from qbank.context import ProjectContext
from qbank.infrastructure import FileAssetRepository
from qbank.models import SavedViewKind
from qbank.papers import load_paper


class ProjectSpecialViews:
    """Resolve redraw and current-paper membership without persisting relations."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def question_ids(self, kind: SavedViewKind) -> frozenset[str]:
        """Return IDs for one project-derived built-in query view."""
        if kind == SavedViewKind.NEEDS_REDRAW:
            repository = FileAssetRepository(self.context)
            return frozenset(
                manifest.question_id
                for manifest in repository.list(strict=False)
                if manifest.status.value == "needs_redraw"
            )
        if kind == SavedViewKind.CURRENT_PAPER:
            path = self.context.paths.papers / "demo-paper.yaml"
            if not path.is_file():
                return frozenset()
            paper = load_paper(path)
            return frozenset(
                question.id for section in paper.sections for question in section.questions
            )
        return frozenset()
