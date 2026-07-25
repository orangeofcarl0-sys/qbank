"""Explicit desktop session state independent from Qt selection side effects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SelectionState:
    """Separate the open document from explicit result-list selection."""

    current_id: str | None = None
    selected_ids: tuple[str, ...] = ()
    current_in_results: bool | None = None

    def with_results(self, result_ids: tuple[str, ...], current_id: str | None) -> SelectionState:
        available = set(result_ids)
        return SelectionState(
            current_id=current_id,
            selected_ids=tuple(item for item in self.selected_ids if item in available),
            current_in_results=current_id is None or current_id in available,
        )

    def with_selection(self, selected_ids: tuple[str, ...]) -> SelectionState:
        return SelectionState(
            current_id=self.current_id,
            selected_ids=selected_ids,
            current_in_results=self.current_in_results,
        )


@dataclass(frozen=True, slots=True)
class PaperContext:
    """Explicitly selected paper; an empty context never implies a YAML file."""

    path: Path | None = None
    question_ids: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.path.name if self.path is not None else "未选择试卷"
