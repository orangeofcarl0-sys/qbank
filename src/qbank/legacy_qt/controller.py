"""Qt-independent desktop orchestration through existing qbank services."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, cast

from qbank.application.service import question_matches
from qbank.asset_references import AssetKind, classify_resource_uri
from qbank.assets import (
    AssetService,
    replace_image_uris,
    stable_legacy_asset_id,
)
from qbank.bootstrap import ProjectServices
from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.legacy_qt.state import PaperContext
from qbank.markdown_codec import parse_sections
from qbank.models import (
    QUESTION_CONTENT_FIELDS,
    AssetFormat,
    AssetHistoryEntry,
    AssetMutationResult,
    AssetPackage,
    AssetPackageRepresentation,
    AssetRenderResult,
    AssetStatus,
    DesktopHistoryEntry,
    DesktopNavigationData,
    DesktopPreviewResult,
    DesktopQuestionDocument,
    DesktopQuestionListResult,
    DesktopQuestionSummary,
    DiagnosticCode,
    Paper,
    PaperBuildRequest,
    PatchQuestionResult,
    QueryFilters,
    Question,
    QuestionPatch,
    SavedViewMutationResult,
    TagMutationResult,
    TagOverviewResult,
    TagUsage,
    TaxonomyTag,
)
from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.web_theme import css_variables
from qbank.question_layout import QUESTION_SECTIONS

DesktopView = str
_DESKTOP_METADATA_FIELDS = frozenset(
    {
        "title",
        "type",
        "subject",
        "chapter",
        "topics",
        "difficulty",
        "status",
        "language",
        "source",
    }
)
_FORMAT_BY_SUFFIX = {
    ".png": AssetFormat.PNG,
    ".jpg": AssetFormat.JPEG,
    ".jpeg": AssetFormat.JPEG,
    ".pdf": AssetFormat.PDF,
    ".svg": AssetFormat.SVG,
    ".ipe": AssetFormat.IPE,
    ".tex": AssetFormat.TIKZ,
    ".webp": AssetFormat.WEBP,
    ".gif": AssetFormat.GIF,
    ".bmp": AssetFormat.BMP,
}
_RENDERABLE_FORMATS = frozenset(
    {
        AssetFormat.PNG,
        AssetFormat.JPEG,
        AssetFormat.PDF,
        AssetFormat.SVG,
        AssetFormat.WEBP,
        AssetFormat.GIF,
        AssetFormat.BMP,
        AssetFormat.URL,
    }
)


class InteractiveRenderer(Protocol):
    """Rendering behavior required by the embedded preview."""

    def interactive_markdown_html(
        self,
        markdown: str,
        *,
        asset_bindings: Mapping[str, str],
    ) -> str: ...

    def internal_template(
        self,
        name: str,
        values: Mapping[str, object],
    ) -> str: ...


class DesktopController:
    """Coordinate one desktop session without direct authoritative writes."""

    def __init__(
        self,
        context: ProjectContext,
        services: ProjectServices,
        renderer: InteractiveRenderer,
    ):
        self.context = context
        self.services = services
        self.renderer = renderer
        self.assets = AssetService(context, services.assets)
        self.paper_context = PaperContext()
        self._question_cache: tuple[Question, ...] | None = None
        self._redraw_cache: frozenset[str] | None = None

    @property
    def current_paper_ids(self) -> tuple[str, ...]:
        """Compatibility projection for special saved-view membership."""
        return self.paper_context.question_ids

    @current_paper_ids.setter
    def current_paper_ids(self, values: tuple[str, ...]) -> None:
        self.paper_context = PaperContext(path=self.paper_context.path, question_ids=values)

    def list_questions(
        self,
        *,
        view: DesktopView = "all",
        search: str = "",
        filters: QueryFilters | None = None,
    ) -> list[DesktopQuestionSummary]:
        """Return rows after one named view and the current transient facets."""
        questions, redraw_ids = self._filtered_questions(view, search, filters)
        return [self._summary(question, redraw_ids) for question in questions]

    def navigation_result(
        self,
        *,
        view: DesktopView = "all",
        search: str = "",
        filters: QueryFilters | None = None,
    ) -> DesktopQuestionListResult:
        """Return rows plus tag counts computed without self-filter disappearance."""
        questions, redraw_ids = self._filtered_questions(view, search, filters)
        active = filters or QueryFilters(text=search or None, limit=100_000)
        facet_filters = active.model_copy(update={"topics": [], "excluded_topics": []})
        facet_questions, _ = self._filtered_questions(view, search, facet_filters)
        counts = Counter(topic for question in facet_questions for topic in set(question.topics))
        metadata = self.services.tags.registry().by_slug()
        slugs = set(counts) | set(active.topics) | set(active.excluded_topics)
        tags = [
            TagUsage(
                slug=slug,
                count=count,
                registered=slug in metadata,
                metadata=metadata.get(slug),
            )
            for slug in sorted(slugs)
            for count in (counts.get(slug, 0),)
        ]
        return DesktopQuestionListResult(
            rows=[self._summary(question, redraw_ids) for question in questions],
            tags=tags,
            total=len(questions),
        )

    def _filtered_questions(
        self,
        view: DesktopView,
        search: str,
        filters: QueryFilters | None,
    ) -> tuple[list[Question], set[str]]:
        questions = list(self._questions())
        redraw_ids = self._redraw_question_ids()
        view_name = "current_paper" if view == "paper" else view
        definition = self.services.views.resolve(view_name)
        visible_ids: set[str] | None = None
        if definition.kind.value == "needs_redraw":
            visible_ids = redraw_ids
        elif definition.kind.value == "current_paper":
            visible_ids = set(self.current_paper_ids)
        active = filters or QueryFilters(text=search or None, limit=100_000)
        saved_filter = definition.filters if filters is None else None
        search_ids: set[str] | None = None
        if active.text is not None:
            search_ids = {
                hit.id
                for hit in self.services.questions.search_projection(active.text, limit=100_000)
            }
            active = active.model_copy(update={"text": None})
        matches = [
            question
            for question in questions
            if (saved_filter is None or question_matches(question, saved_filter))
            and (visible_ids is None or question.id in visible_ids)
            and (search_ids is None or question.id in search_ids)
            and question_matches(question, active)
        ]
        return matches, redraw_ids

    def navigation_data(self) -> DesktopNavigationData:
        """Return current saved views and deterministic facet choices."""
        questions = list(self._questions())
        years = sorted(
            {
                int(question.created_at[:4])
                for question in questions
                if question.created_at is not None
            }
        )
        return DesktopNavigationData(
            views=self.services.views.list_views(),
            tags=self.services.tags.list_tags(),
            statuses=sorted({question.status.value for question in questions}),
            question_types=sorted({question.type.value for question in questions}),
            subjects=sorted({question.subject for question in questions}),
            chapters=sorted(
                {question.chapter for question in questions if question.chapter is not None}
            ),
            languages=sorted({question.language for question in questions}),
            years=years,
        )

    def tag_suggestions(self, text: str = "", *, limit: int = 20) -> list[TagUsage]:
        """Return registry-aware topic suggestions for the Inspector."""
        return self.services.tags.suggestions(text, limit=limit)

    def list_tags(self) -> list[TagUsage]:
        """Return all tag registry rows with authoritative counts."""
        return self.services.tags.list_tags()

    def possible_tag_synonyms(self, value: str, *, limit: int = 5) -> list[TagUsage]:
        """Return close registry matches before Studio creates a pending tag."""
        return self.services.tags.possible_synonyms(value, limit=limit)

    def tag_overview(self, *, top_n: int = 12) -> TagOverviewResult:
        """Return lightweight charts derived from authoritative question topics."""
        return self.services.tags.overview(top_n=top_n)

    def save_view(
        self, name: str, filters: QueryFilters, *, dry_run: bool = False
    ) -> SavedViewMutationResult:
        """Persist the current transient filters as a reusable query view."""
        return self.services.views.save(name, filters, dry_run=dry_run)

    def rename_view(self, old: str, new: str, *, dry_run: bool = False) -> SavedViewMutationResult:
        """Rename one user view through the application service."""
        return self.services.views.rename(old, new, dry_run=dry_run)

    def delete_view(self, name: str, *, dry_run: bool = False) -> SavedViewMutationResult:
        """Delete one user view through the application service."""
        return self.services.views.delete(name, dry_run=dry_run)

    def bulk_edit_topics(
        self,
        question_ids: list[str],
        *,
        add: list[str] | None = None,
        remove: list[str] | None = None,
        dry_run: bool = False,
    ) -> TagMutationResult:
        """Apply a multi-selection topic edit through one atomic use case."""
        result = self.services.tags.bulk_edit(
            question_ids,
            add=add or [],
            remove=remove or [],
            dry_run=dry_run,
            command="qbank desktop bulk tags",
        )
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def rename_tag(self, old: str, new: str, *, dry_run: bool = False) -> TagMutationResult:
        """Plan or commit a global tag rename."""
        result = self.services.tags.rename(
            old, new, dry_run=dry_run, command="qbank desktop tag rename"
        )
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def merge_tag(self, source: str, target: str, *, dry_run: bool = False) -> TagMutationResult:
        """Plan or commit a global tag merge."""
        result = self.services.tags.merge(
            source, target, dry_run=dry_run, command="qbank desktop tag merge"
        )
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def delete_tag(self, slug: str, *, dry_run: bool = False) -> TagMutationResult:
        """Plan or commit a global tag deletion."""
        result = self.services.tags.delete(
            slug, dry_run=dry_run, command="qbank desktop tag delete"
        )
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def update_tag(self, tag: TaxonomyTag, *, dry_run: bool = False) -> TagMutationResult:
        """Plan or commit tag display metadata changes."""
        return self.services.tags.update_tag(
            tag, dry_run=dry_run, command="qbank desktop tag update"
        )

    def undo_tag(self, token: str, *, dry_run: bool = False) -> TagMutationResult:
        """Plan or commit a safe inverse tag history event."""
        return self.services.tags.undo(token, dry_run=dry_run, command="qbank desktop tag undo")

    def load_question(self, question_id: str) -> DesktopQuestionDocument:
        """Load one editable body plus assets and asset history."""
        question = self.services.questions.get_question(question_id)
        assets = self.services.assets.list_assets(question_id).assets
        asset_history = self.services.assets.history(question_id).events
        history = self.services.history.timeline(question_id, asset_history)
        return DesktopQuestionDocument(
            question=question,
            source=question_body_source(question),
            assets=assets,
            history=cast(list[DesktopHistoryEntry | AssetHistoryEntry], history),
            asset_items=self.assets.desktop_items(question, assets, asset_history),
        )

    def validate_source(
        self,
        question_id: str,
        source: str,
        metadata: Mapping[str, object] | None = None,
    ) -> PatchQuestionResult:
        """Validate an editor buffer through the structured patch use case."""
        patch = self._patch(question_id, source, metadata)
        return self.services.questions.patch_question(
            question_id,
            patch,
            dry_run=True,
            command="qbank desktop validate",
        )

    def save_source(
        self,
        question_id: str,
        source: str,
        metadata: Mapping[str, object] | None = None,
    ) -> PatchQuestionResult:
        """Dry-run and then commit one editor buffer through qbank mutations."""
        patch = self._patch(question_id, source, metadata)
        planned = self.services.studio.save_question(
            question_id,
            patch,
            dry_run=True,
        )
        if not planned.ok:
            return planned
        committed = self.services.studio.save_question(
            question_id,
            patch,
            dry_run=False,
        )
        self.invalidate_repository_cache()
        return committed

    def preview_source(
        self,
        question_id: str,
        source: str,
        metadata: Mapping[str, object] | None = None,
        *,
        theme: ThemeName = "light",
    ) -> DesktopPreviewResult:
        """Render an unsaved editor buffer with interactive logical images."""
        candidate = self._candidate(question_id, source, metadata)
        projected, warnings, bindings = self.assets.project_question_with_bindings(
            candidate,
            target="preview",
        )
        values = {
            "question": projected,
            "sections": [
                {
                    "title": section.title,
                    "field": section.field,
                    "html": self.renderer.interactive_markdown_html(
                        getattr(projected, section.field),
                        asset_bindings=bindings,
                    ),
                }
                for section in QUESTION_SECTIONS
            ],
            "assets": self.services.assets.list_assets(question_id).assets,
            "theme": theme,
            "theme_css": css_variables(theme),
        }
        return DesktopPreviewResult(
            html=self.renderer.internal_template("desktop/preview.html.j2", values),
            warnings=warnings,
        )

    def load_current_paper(self, path: Path | None = None) -> tuple[str, ...]:
        """Select only an explicitly supplied paper for the navigation view."""
        if path is None:
            self.paper_context = PaperContext()
            return ()
        selected = path.resolve()
        ids = self.services.studio_project.paper_ids(selected)
        self.paper_context = PaperContext(path=selected, question_ids=ids)
        return ids

    def list_papers(self) -> list[Path]:
        """Return paper definitions without changing the current selection."""
        return self.services.studio_project.list_papers()

    def project_status(self):
        """Return read-only project validation and index state for the title bar."""
        return self.services.studio_project.status()

    def create_question(self, question_id: str, title: str, *, dry_run: bool):
        """Create a schema-valid draft placeholder through the normal add transaction."""
        result = self.services.studio_project.create_question(question_id, title, dry_run=dry_run)
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def copy_question(self, source_id: str, new_id: str, *, dry_run: bool):
        """Copy one question as an independently reviewed draft."""
        result = self.services.studio_project.copy_question(source_id, new_id, dry_run=dry_run)
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def import_questions(self, path: Path, *, dry_run: bool):
        """Import JSON or JSONL through the batch transaction."""
        result = self.services.studio_project.import_questions(path, dry_run=dry_run)
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def delete_question(self, question_id: str, *, dry_run: bool):
        """Preview or commit an authoritative question deletion."""
        result = self.services.studio_project.delete_question(question_id, dry_run=dry_run)
        if not dry_run:
            self.invalidate_repository_cache()
        return result

    def create_paper(
        self,
        path: Path,
        title: str,
        question_ids: list[str],
        *,
        dry_run: bool,
    ) -> Paper:
        """Create an explicitly named paper from selected questions."""
        paper = self.services.studio_project.create_paper(
            path, title, question_ids, dry_run=dry_run
        )
        if not dry_run:
            self.load_current_paper(path)
        return paper

    def add_to_current_paper(self, question_ids: list[str], *, dry_run: bool) -> Paper:
        """Add unique questions to the explicitly selected paper."""
        path = self.paper_context.path
        if path is None:
            raise DataValidationError("select or create a paper first")
        updated = self.services.studio_project.add_to_paper(path, question_ids, dry_run=dry_run)
        if not dry_run:
            self.load_current_paper(path)
        return updated

    def validate_current_paper(self):
        """Validate the explicitly selected paper."""
        if self.paper_context.path is None:
            raise DataValidationError("select or create a paper first")
        return self.services.studio_project.validate_paper(self.paper_context.path)

    def build_current_paper(self, request: PaperBuildRequest):
        """Build the explicitly selected paper through the shared renderer."""
        if self.paper_context.path is None:
            raise DataValidationError("select or create a paper first")
        return self.services.studio_project.build_paper(self.paper_context.path, request)

    def begin_asset_edit(self, question_id: str, asset_id: str) -> str:
        """Dry-run and open a versioned preferred-editor working copy."""
        self.services.assets.begin_edit_session(question_id, asset_id, dry_run=True)
        result = self.services.assets.begin_edit_session(question_id, asset_id, dry_run=False)
        return result.target

    def reconcile_asset(self, question_id: str, asset_id: str) -> AssetMutationResult:
        """Reconcile an externally saved editor working copy through the asset service."""
        planned = self.services.assets.reconcile_editor_change(
            question_id,
            asset_id,
            dry_run=True,
        )
        if not planned.ok:
            return planned
        return self.services.assets.reconcile_editor_change(
            question_id,
            asset_id,
            dry_run=False,
        )

    def render_asset(self, question_id: str, asset_id: str) -> AssetRenderResult:
        """Dry-run and render PDF/SVG/PNG through the registered Ipe adapter."""
        formats = (AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG)
        self.services.assets.render_asset(
            question_id,
            asset_id,
            formats=formats,
            dry_run=True,
        )
        return self.services.assets.render_asset(
            question_id,
            asset_id,
            formats=formats,
            dry_run=False,
        )

    def open_original(self, question_id: str, asset_id: str) -> None:
        """Dry-run and open a containment-checked original reference."""
        self.services.assets.open_original(question_id, asset_id, dry_run=True)
        self.services.assets.open_original(question_id, asset_id, dry_run=False)

    def show_asset_directory(self, question_id: str, asset_id: str) -> None:
        """Dry-run and reveal the registered asset directory."""
        self.services.assets.open_asset_directory(question_id, asset_id, dry_run=True)
        self.services.assets.open_asset_directory(question_id, asset_id, dry_run=False)

    def replace_asset(
        self,
        question_id: str,
        asset_id: str,
        source: str,
        *,
        name: str | None = None,
    ) -> AssetMutationResult:
        """Replace from a local file or data URI while retaining prior versions."""
        representation, package_root = _replacement_input(source, name=name)
        self.services.assets.replace(
            question_id,
            asset_id,
            representation,
            package_root,
            dry_run=True,
        )
        return self.services.assets.replace(
            question_id,
            asset_id,
            representation,
            package_root,
            dry_run=False,
        )

    def create_asset(
        self,
        question_id: str,
        source: str,
        *,
        name: str | None = None,
    ) -> AssetMutationResult:
        """Create a logical asset and declare its stable reference on the question."""
        representation, package_root = _replacement_input(source, name=name)
        asset_id = self._new_asset_id(question_id, name or representation.representation_id)
        package = AssetPackage(
            schema_version="1.0",
            question_id=question_id,
            asset_id=asset_id,
            role="illustration",
            representations=[representation],
            provenance={"producer": "qbank desktop", "input_name": name},
            suggested_editor=(
                representation.representation_id if representation.editable else None
            ),
            suggested_render=(
                representation.representation_id
                if representation.format in _RENDERABLE_FORMATS
                else None
            ),
            status=AssetStatus.RAW,
        )
        question = self.services.questions.get_question(question_id)
        patch = QuestionPatch(set={"assets": [*question.assets, f"qbank-asset:{asset_id}"]})
        return self._commit_new_asset(
            package,
            package_root,
            patch,
            command="qbank desktop create asset",
        )

    def ensure_logical_asset(self, question_id: str, asset_id: str) -> str:
        """Materialize a deterministic pending ID for one legacy image URI."""
        existing = {item.asset_id for item in self.services.assets.list_assets(question_id).assets}
        if asset_id in existing:
            return asset_id
        question = self.services.questions.get_question(question_id)
        raw = next(
            (
                reference
                for reference in question.assets
                if stable_legacy_asset_id(reference) == asset_id
            ),
            None,
        )
        if raw is None:
            raise DataValidationError(f"asset_not_found: unknown preview asset: {asset_id}")
        representation, package_root = self._legacy_representation(raw)
        package = AssetPackage(
            schema_version="1.0",
            question_id=question_id,
            asset_id=asset_id,
            role="legacy-image",
            representations=[representation],
            provenance={
                "producer": "qbank desktop legacy normalization",
                "legacy_references": [raw],
            },
            suggested_editor=(
                representation.representation_id if representation.editable else None
            ),
            suggested_render=(
                representation.representation_id
                if representation.format in _RENDERABLE_FORMATS
                else None
            ),
            status=AssetStatus.RAW,
        )
        patch = self._legacy_reference_patch(question, raw, asset_id)
        self._commit_new_asset(
            package,
            package_root,
            patch,
            command="qbank desktop normalize legacy asset",
        )
        return asset_id

    def _commit_new_asset(
        self,
        package: AssetPackage,
        package_root: Path,
        patch: QuestionPatch,
        *,
        command: str,
    ) -> AssetMutationResult:
        """Commit a new asset and compensate if its question declaration fails."""
        self.services.assets.ingest_package(package, package_root, dry_run=True)
        self._preflight_planned_asset_patch(package, patch, command)
        result = self.services.assets.ingest_package(package, package_root, dry_run=False)
        try:
            self._commit_question_patch(package.question_id, patch, command)
        except Exception as original_error:
            canonical = f"qbank-asset:{package.asset_id}"
            try:
                current = self.services.questions.get_question(package.question_id)
                if canonical not in current.assets:
                    self.services.assets.discard_new_asset(
                        package.question_id,
                        package.asset_id,
                    )
            except Exception as rollback_error:
                original_error.add_note(f"asset rollback failed: {rollback_error}")
            raise
        return result

    def _preflight_planned_asset_patch(
        self,
        package: AssetPackage,
        patch: QuestionPatch,
        command: str,
    ) -> None:
        planned = self.services.questions.patch_question(
            package.question_id,
            patch,
            dry_run=True,
            command=command,
        )
        expected_reference = f"/{package.asset_id}"
        blocking = [
            item
            for item in planned.validation_errors
            if not (
                item.code == DiagnosticCode.ASSET_NOT_FOUND and expected_reference in item.message
            )
        ]
        if blocking:
            messages = "; ".join(item.message for item in blocking)
            raise DataValidationError(f"desktop asset declaration failed validation: {messages}")

    def _commit_question_patch(
        self,
        question_id: str,
        patch: QuestionPatch,
        command: str,
    ) -> None:
        planned = self.services.questions.patch_question(
            question_id,
            patch,
            dry_run=True,
            command=command,
        )
        if not planned.ok:
            raise DataValidationError("desktop asset declaration failed validation")
        committed = self.services.questions.patch_question(
            question_id,
            patch,
            dry_run=False,
            command=command,
        )
        if not committed.ok:
            raise DataValidationError("desktop asset declaration failed during commit")
        self.invalidate_repository_cache()

    def set_preferred_render(
        self,
        question_id: str,
        asset_id: str,
        representation_id: str,
    ) -> AssetMutationResult:
        """Dry-run and set one registered preferred render."""
        self.services.assets.set_preference(
            question_id,
            asset_id,
            representation_id,
            kind="render",
            dry_run=True,
        )
        return self.services.assets.set_preference(
            question_id,
            asset_id,
            representation_id,
            kind="render",
            dry_run=False,
        )

    def restore_asset(self, question_id: str, asset_id: str) -> AssetMutationResult:
        """Dry-run and restore previous preferences."""
        self.services.assets.restore_previous(question_id, asset_id, dry_run=True)
        return self.services.assets.restore_previous(question_id, asset_id, dry_run=False)

    def _patch(
        self,
        question_id: str,
        source: str,
        metadata: Mapping[str, object] | None,
    ) -> QuestionPatch:
        candidate = self._candidate(question_id, source, metadata)
        current = self.services.questions.get_question(question_id)
        updates = {
            field: getattr(candidate, field)
            for field in (*QUESTION_CONTENT_FIELDS, *_DESKTOP_METADATA_FIELDS)
            if field != "topics" and getattr(candidate, field) != getattr(current, field)
        }
        return QuestionPatch(
            set=updates,
            add_topics=[item for item in candidate.topics if item not in current.topics],
            remove_topics=[item for item in current.topics if item not in candidate.topics],
        )

    def _candidate(
        self,
        question_id: str,
        source: str,
        metadata: Mapping[str, object] | None,
    ) -> Question:
        current = self.services.questions.get_question(question_id)
        content, duplicates = parse_sections(source)
        if duplicates:
            raise DataValidationError(f"duplicate_section: {', '.join(dict.fromkeys(duplicates))}")
        values = current.model_dump(mode="python")
        values.update(content)
        values.update(_normalized_metadata(metadata))
        return Question.model_validate(values)

    def _redraw_question_ids(self) -> set[str]:
        if self._redraw_cache is not None:
            return set(self._redraw_cache)
        redraw: set[str] = set()
        for question in self._questions():
            for manifest in self.services.assets.list_assets(question.id).assets:
                unfinished = manifest.status in {
                    AssetStatus.RAW,
                    AssetStatus.NEEDS_REDRAW,
                    AssetStatus.EDITING,
                    AssetStatus.FAILED,
                }
                if unfinished or any(item.stale for item in manifest.representations):
                    redraw.add(question.id)
        self._redraw_cache = frozenset(redraw)
        return redraw

    def _questions(self) -> tuple[Question, ...]:
        if self._question_cache is None:
            self._question_cache = tuple(
                self.services.questions.query_questions(QueryFilters(limit=100_000))
            )
        return self._question_cache

    def invalidate_repository_cache(self) -> None:
        """Invalidate projections after a committed authoritative mutation."""
        self._question_cache = None
        self._redraw_cache = None

    def _matches_view(
        self,
        question: Question,
        view: DesktopView,
        redraw_ids: set[str],
    ) -> bool:
        if view == "draft":
            return question.status.value == "draft"
        if view == "needs_redraw":
            return question.id in redraw_ids
        if view == "paper":
            return question.id in self.current_paper_ids
        return True

    @staticmethod
    def _summary(question: Question, redraw_ids: set[str]) -> DesktopQuestionSummary:
        return DesktopQuestionSummary(
            id=question.id,
            title=question.title,
            subject=question.subject,
            status=question.status.value,
            question_type=question.type.value,
            difficulty=question.difficulty,
            needs_redraw=question.id in redraw_ids,
        )

    def _new_asset_id(self, question_id: str, name: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(name).stem).strip("-") or "figure"
        occupied = {
            manifest.asset_id for manifest in self.services.assets.list_assets(question_id).assets
        }
        candidate = base
        index = 2
        while candidate in occupied:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    def _legacy_representation(
        self,
        raw: str,
    ) -> tuple[AssetPackageRepresentation, Path]:
        reference = classify_resource_uri(raw)
        if reference.kind == AssetKind.LOCAL and reference.normalized is not None:
            representation, root = _replacement_input(
                str((self.context.root / reference.normalized).resolve()),
                name="legacy-original",
            )
            return representation.model_copy(update={"purpose": "original"}), root
        if reference.kind == AssetKind.EXTERNAL:
            return (
                AssetPackageRepresentation(
                    representation_id="legacy-original",
                    format=AssetFormat.URL,
                    url=raw,
                    purpose="original",
                    editable=False,
                ),
                self.context.root,
            )
        raise DataValidationError(f"invalid_resource_uri: cannot normalize legacy asset: {raw}")

    def _legacy_reference_patch(
        self,
        question: Question,
        raw: str,
        asset_id: str,
    ) -> QuestionPatch:
        canonical = f"qbank-asset:{asset_id}"
        updates: dict[str, object] = {
            "assets": [canonical if item == raw else item for item in question.assets],
        }
        for field in QUESTION_CONTENT_FIELDS:
            updates[field] = replace_image_uris(
                getattr(question, field),
                {raw: canonical},
            )
        return QuestionPatch(set=updates)


def question_body_source(question: Question) -> str:
    """Serialize only canonical editable body sections."""
    chunks = [
        f"## {section.title}\n\n{getattr(question, section.field).strip()}\n"
        for section in QUESTION_SECTIONS
    ]
    return "\n".join(chunks).rstrip() + "\n"


def _normalized_metadata(metadata: Mapping[str, object] | None) -> dict[str, object]:
    if metadata is None:
        return {}
    values = {key: value for key, value in metadata.items() if key in _DESKTOP_METADATA_FIELDS}
    topics = values.get("topics")
    if isinstance(topics, str):
        values["topics"] = [item.strip() for item in topics.split(",") if item.strip()]
    difficulty = values.get("difficulty")
    if isinstance(difficulty, str) and difficulty.strip():
        values["difficulty"] = int(difficulty)
    chapter = values.get("chapter")
    if isinstance(chapter, str) and not chapter.strip():
        values["chapter"] = None
    return values


def _replacement_input(
    source: str,
    *,
    name: str | None,
) -> tuple[AssetPackageRepresentation, Path]:
    if source.startswith("data:"):
        format_ = _format_from_data_uri(source, name)
        return (
            AssetPackageRepresentation(
                representation_id=_representation_id(name or "clipboard"),
                format=format_,
                data_uri=source,
                purpose="replacement",
                editable=format_ in {AssetFormat.IPE, AssetFormat.TIKZ},
            ),
            Path.cwd(),
        )
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise DataValidationError(f"asset_missing: replacement file does not exist: {path}")
    format_ = _FORMAT_BY_SUFFIX.get(path.suffix.lower(), AssetFormat.OTHER)
    return (
        AssetPackageRepresentation(
            representation_id=_representation_id(name or path.stem),
            format=format_,
            path=path.name,
            purpose="replacement",
            editable=format_ in {AssetFormat.IPE, AssetFormat.TIKZ},
        ),
        path.parent,
    )


def _format_from_data_uri(source: str, name: str | None) -> AssetFormat:
    mime = source[5:].split(";", maxsplit=1)[0].lower()
    by_mime = {
        "image/png": AssetFormat.PNG,
        "image/jpeg": AssetFormat.JPEG,
        "image/svg+xml": AssetFormat.SVG,
        "image/webp": AssetFormat.WEBP,
        "image/gif": AssetFormat.GIF,
        "image/bmp": AssetFormat.BMP,
        "application/pdf": AssetFormat.PDF,
    }
    if mime in by_mime:
        return by_mime[mime]
    return _FORMAT_BY_SUFFIX.get(Path(name or "").suffix.lower(), AssetFormat.OTHER)


def _representation_id(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(name).stem).strip("-")
    return value or "desktop-source"
