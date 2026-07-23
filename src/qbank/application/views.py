"""Persistent saved question-view use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from qbank.application.locking import RepositoryWriteLockPort
from qbank.application.ports import QuestionRepositoryPort
from qbank.application.service import question_matches
from qbank.errors import ConflictError, DataValidationError, QuestionNotFoundError
from qbank.models import (
    QueryFilters,
    Question,
    QuestionStatus,
    SavedView,
    SavedViewKind,
    SavedViewMutationResult,
    SavedViewRegistry,
    Taxonomy,
)


class SavedViewStorePort(Protocol):
    """Persistent user-view registry boundary."""

    def load(self) -> SavedViewRegistry: ...

    def save(self, registry: SavedViewRegistry) -> None: ...


class SpecialViewPort(Protocol):
    """Resolve project-derived built-in view membership."""

    def question_ids(self, kind: SavedViewKind) -> frozenset[str]: ...


class ViewTaxonomyPort(Protocol):
    """Resolve historical aliases used by persisted view filters."""

    def load(self) -> Taxonomy: ...


BUILTIN_VIEWS = (
    SavedView(name="all", protected=True),
    SavedView(
        name="draft",
        filters=QueryFilters(status=QuestionStatus.DRAFT),
        protected=True,
    ),
    SavedView(name="needs_redraw", kind=SavedViewKind.NEEDS_REDRAW, protected=True),
    SavedView(name="current_paper", kind=SavedViewKind.CURRENT_PAPER, protected=True),
)


@dataclass(frozen=True, slots=True)
class SavedViewService:
    """List, persist, and apply named query definitions."""

    repository: QuestionRepositoryPort
    store: SavedViewStorePort
    special: SpecialViewPort
    taxonomy: ViewTaxonomyPort
    lock: RepositoryWriteLockPort | None = None

    def list_views(self) -> list[SavedView]:
        """Return fixed built-ins followed by user views."""
        return [
            *BUILTIN_VIEWS,
            *(self._canonical_view(view) for view in self.store.load().views),
        ]

    def resolve(self, name: str) -> SavedView:
        """Resolve a view by its case-insensitive stable name."""
        folded = name.strip().casefold()
        for view in self.list_views():
            if view.name.casefold() == folded:
                return view
        raise QuestionNotFoundError(f"saved view not found: {name}")

    def apply(self, name: str) -> list[Question]:
        """Apply filters and optional project-derived membership."""
        view = self.resolve(name)
        snapshot = self.repository.scan()
        snapshot.require_consistent()
        special_ids = (
            None if view.kind == SavedViewKind.FILTER else self.special.question_ids(view.kind)
        )
        matches = [
            record.question
            for record in snapshot.records
            if question_matches(record.question, view.filters)
            and (special_ids is None or record.question.id in special_ids)
        ]
        return sorted(matches, key=lambda question: question.id)

    def save(
        self,
        name: str,
        filters: QueryFilters,
        *,
        dry_run: bool,
    ) -> SavedViewMutationResult:
        """Create or replace one user view."""
        if any(view.name.casefold() == name.strip().casefold() for view in BUILTIN_VIEWS):
            raise ConflictError(f"built-in view cannot be replaced: {name}")
        registry = self.store.load()
        view = SavedView(name=name, filters=self._canonical_filters(filters))
        views = [item for item in registry.views if item.name.casefold() != view.name.casefold()]
        views.append(view)
        if not dry_run:
            self._save_registry(registry, SavedViewRegistry(views=views), "view_save")
        return SavedViewMutationResult(ok=True, dry_run=dry_run, action="save", view=view)

    def rename(self, old: str, new: str, *, dry_run: bool) -> SavedViewMutationResult:
        """Rename one user-created view."""
        current = self.resolve(old)
        if current.protected:
            raise DataValidationError(f"built-in view cannot be renamed: {old}")
        if any(view.name.casefold() == new.strip().casefold() for view in self.list_views()):
            raise ConflictError(f"saved view already exists: {new}")
        replacement = current.model_copy(update={"name": new.strip()})
        registry = self.store.load()
        views = [replacement if view.name == current.name else view for view in registry.views]
        if not dry_run:
            self._save_registry(registry, SavedViewRegistry(views=views), "view_rename")
        return SavedViewMutationResult(ok=True, dry_run=dry_run, action="rename", view=replacement)

    def delete(self, name: str, *, dry_run: bool) -> SavedViewMutationResult:
        """Delete one user-created view while preserving fixed entries."""
        current = self.resolve(name)
        if current.protected:
            raise DataValidationError(f"built-in view cannot be deleted: {name}")
        registry = self.store.load()
        views = [view for view in registry.views if view.name != current.name]
        if len(views) == len(registry.views):
            raise QuestionNotFoundError(f"saved view not found: {name}")
        if not dry_run:
            self._save_registry(registry, SavedViewRegistry(views=views), "view_delete")
        return SavedViewMutationResult(ok=True, dry_run=dry_run, action="delete", view=current)

    def _canonical_view(self, view: SavedView) -> SavedView:
        filters = self._canonical_filters(view.filters)
        return view if filters == view.filters else view.model_copy(update={"filters": filters})

    def _save_registry(
        self,
        expected: SavedViewRegistry,
        updated: SavedViewRegistry,
        operation: str,
    ) -> None:
        if self.lock is None:
            self.store.save(updated)
            return
        with self.lock.hold(operation):
            if self.store.load() != expected:
                raise ConflictError("saved views changed before the protected commit")
            self.store.save(updated)

    def _canonical_filters(self, filters: QueryFilters) -> QueryFilters:
        registry = self.taxonomy.load()
        values = filters.model_dump()
        values["topics"] = list(
            dict.fromkeys(registry.resolve(topic) or topic for topic in filters.topics)
        )
        values["excluded_topics"] = list(
            dict.fromkeys(registry.resolve(topic) or topic for topic in filters.excluded_topics)
        )
        return QueryFilters.model_validate(values)
