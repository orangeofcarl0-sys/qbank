"""Qt-independent desktop orchestration through existing qbank services."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol

from qbank.asset_references import AssetKind, classify_resource_uri
from qbank.assets import (
    AssetService,
    replace_image_uris,
    stable_legacy_asset_id,
)
from qbank.bootstrap import ProjectServices
from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.markdown_codec import parse_sections
from qbank.models import (
    QUESTION_CONTENT_FIELDS,
    AssetFormat,
    AssetMutationResult,
    AssetPackage,
    AssetPackageRepresentation,
    AssetRenderResult,
    AssetStatus,
    DesktopPreviewResult,
    DesktopQuestionDocument,
    DesktopQuestionSummary,
    PatchQuestionResult,
    Question,
    QuestionPatch,
)
from qbank.papers import load_paper
from qbank.question_layout import QUESTION_SECTIONS

DesktopView = Literal["all", "draft", "needs_redraw", "paper"]
_DESKTOP_METADATA_FIELDS = frozenset(
    {"title", "type", "subject", "chapter", "topics", "difficulty", "status", "language"}
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
        self.current_paper_ids: tuple[str, ...] = ()

    def list_questions(
        self,
        *,
        view: DesktopView = "all",
        search: str = "",
    ) -> list[DesktopQuestionSummary]:
        """Return navigation rows for the selected lightweight view."""
        questions = self.services.questions.query_questions()
        redraw_ids = self._redraw_question_ids()
        normalized_search = search.strip().casefold()
        rows = [
            self._summary(question, redraw_ids)
            for question in questions
            if self._matches_view(question, view, redraw_ids)
            and _matches_search(question, normalized_search)
        ]
        return rows

    def load_question(self, question_id: str) -> DesktopQuestionDocument:
        """Load one editable body plus assets and asset history."""
        question = self.services.questions.get_question(question_id)
        assets = self.services.assets.list_assets(question_id).assets
        history = self.services.assets.history(question_id).events
        return DesktopQuestionDocument(
            question=question,
            source=question_body_source(question),
            assets=assets,
            history=history,
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
        planned = self.services.questions.patch_question(
            question_id,
            patch,
            dry_run=True,
            command="qbank desktop save",
        )
        if not planned.ok:
            return planned
        return self.services.questions.patch_question(
            question_id,
            patch,
            dry_run=False,
            command="qbank desktop save",
        )

    def preview_source(
        self,
        question_id: str,
        source: str,
        metadata: Mapping[str, object] | None = None,
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
        }
        return DesktopPreviewResult(
            html=self.renderer.internal_template("desktop/preview.html.j2", values),
            warnings=warnings,
        )

    def load_current_paper(self, path: Path | None = None) -> tuple[str, ...]:
        """Select a paper for the navigation view using qbank's paper loader."""
        selected = path or _default_paper(self.context.paths.papers)
        if selected is None:
            self.current_paper_ids = ()
            return ()
        paper = load_paper(selected)
        self.current_paper_ids = tuple(
            item.id for section in paper.sections for item in section.questions
        )
        return self.current_paper_ids

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
        self.services.assets.ingest_package(package, package_root, dry_run=True)
        result = self.services.assets.ingest_package(package, package_root, dry_run=False)
        self._declare_asset(question_id, asset_id)
        return result

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
        self.services.assets.ingest_package(package, package_root, dry_run=True)
        self.services.assets.ingest_package(package, package_root, dry_run=False)
        self._replace_legacy_reference(question, raw, asset_id)
        return asset_id

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
        redraw: set[str] = set()
        for question in self.services.questions.query_questions():
            for manifest in self.services.assets.list_assets(question.id).assets:
                unfinished = manifest.status in {
                    AssetStatus.RAW,
                    AssetStatus.NEEDS_REDRAW,
                    AssetStatus.EDITING,
                    AssetStatus.FAILED,
                }
                if unfinished or any(item.stale for item in manifest.representations):
                    redraw.add(question.id)
        return redraw

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

    def _declare_asset(self, question_id: str, asset_id: str) -> None:
        question = self.services.questions.get_question(question_id)
        reference = f"qbank-asset:{asset_id}"
        patch = QuestionPatch(set={"assets": [*question.assets, reference]})
        planned = self.services.questions.patch_question(
            question_id,
            patch,
            dry_run=True,
            command="qbank desktop create asset",
        )
        if not planned.ok:
            raise DataValidationError("desktop asset declaration failed validation")
        self.services.questions.patch_question(
            question_id,
            patch,
            dry_run=False,
            command="qbank desktop create asset",
        )

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

    def _replace_legacy_reference(
        self,
        question: Question,
        raw: str,
        asset_id: str,
    ) -> None:
        canonical = f"qbank-asset:{asset_id}"
        updates: dict[str, object] = {
            "assets": [canonical if item == raw else item for item in question.assets],
        }
        for field in QUESTION_CONTENT_FIELDS:
            updates[field] = replace_image_uris(
                getattr(question, field),
                {raw: canonical},
            )
        patch = QuestionPatch(set=updates)
        planned = self.services.questions.patch_question(
            question.id,
            patch,
            dry_run=True,
            command="qbank desktop normalize legacy asset",
        )
        if not planned.ok:
            raise DataValidationError("desktop legacy normalization failed validation")
        self.services.questions.patch_question(
            question.id,
            patch,
            dry_run=False,
            command="qbank desktop normalize legacy asset",
        )


def question_body_source(question: Question) -> str:
    """Serialize only canonical editable body sections."""
    chunks = [
        f"## {section.title}\n\n{getattr(question, section.field).strip()}\n"
        for section in QUESTION_SECTIONS
    ]
    return "\n".join(chunks).rstrip() + "\n"


def _matches_search(question: Question, search: str) -> bool:
    if not search:
        return True
    haystack = " ".join(
        (
            question.id,
            question.title,
            question.subject,
            question.stem_md,
            " ".join(question.topics),
        )
    ).casefold()
    return search in haystack


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


def _default_paper(root: Path) -> Path | None:
    demo = root / "demo-paper.yaml"
    if demo.is_file():
        return demo
    return next(iter(sorted(root.rglob("*.yaml"), key=lambda item: item.as_posix())), None)
