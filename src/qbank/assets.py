"""Shared Markdown image classification, extraction, and copying."""

from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from qbank.application.assets import AssetApplicationService
from qbank.asset_references import (
    AssetKind,
    AssetReference,
    classify_resource_uri,
    extract_image_resources,
)
from qbank.context import ProjectContext
from qbank.domain import AssetTarget
from qbank.models import (
    AssetCapabilities,
    AssetFormat,
    AssetHistoryEntry,
    AssetManifest,
    DesktopAssetItem,
    Diagnostic,
    DiagnosticCode,
    Question,
)
from qbank.question_layout import QUESTION_CONTENT_FIELDS

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp"})


class AssetService:
    """Resolve and copy validated declared assets consistently."""

    def __init__(
        self,
        context: ProjectContext,
        registry: AssetApplicationService | None = None,
    ):
        self.context = context
        self.registry = registry or _default_registry(context)

    def source(self, normalized: str) -> Path:
        """Resolve one local resource path against the project."""
        return (self.context.root / normalized).resolve()

    def relative_to_assets(self, normalized: str) -> Path:
        """Return an asset's path relative to the configured assets root."""
        return self.source(normalized).relative_to(self.context.paths.assets)

    def desktop_items(
        self,
        question: Question,
        manifests: list[AssetManifest],
        history: list[AssetHistoryEntry],
    ) -> list[DesktopAssetItem]:
        """Describe every question resource after containment and capability checks."""
        references = list(question.assets)
        references.extend(raw for raw in extract_image_resources(question) if raw not in references)
        by_id = {manifest.asset_id: manifest for manifest in manifests}
        history_ids = {event.asset_id for event in history}
        seen_assets: set[str] = set()
        items: list[DesktopAssetItem] = []
        for raw in references:
            item = self._desktop_reference_item(
                question.id,
                raw,
                raw in question.assets,
                by_id,
                history_ids,
            )
            if item.asset_id is not None and item.kind == "logical":
                if item.asset_id in seen_assets:
                    continue
                seen_assets.add(item.asset_id)
            items.append(item)
        for manifest in manifests:
            if manifest.asset_id not in seen_assets:
                items.append(self._logical_desktop_item(manifest, history_ids, declared=False))
        return items

    def _desktop_reference_item(
        self,
        question_id: str,
        raw: str,
        declared: bool,
        manifests: Mapping[str, AssetManifest],
        history_ids: set[str],
    ) -> DesktopAssetItem:
        reference = classify_resource_uri(raw)
        if reference.kind == AssetKind.LOGICAL and reference.asset_id is not None:
            manifest = manifests.get(reference.asset_id)
            if manifest is not None:
                return self._logical_desktop_item(manifest, history_ids, declared=declared)
            return _invalid_desktop_item(
                raw,
                DiagnosticCode.ASSET_NOT_FOUND,
                f"logical asset manifest does not exist: {question_id}/{reference.asset_id}",
                asset_id=reference.asset_id,
            )
        if reference.kind == AssetKind.LOCAL and reference.normalized is not None:
            return self._local_desktop_item(raw, reference.normalized, declared)
        if reference.kind == AssetKind.EXTERNAL:
            return DesktopAssetItem(
                kind="external",
                reference=raw,
                display_name=raw,
                asset_id=stable_legacy_asset_id(raw),
                exists=True,
                declared=declared,
                diagnostic=Diagnostic(
                    severity="warning",
                    code=DiagnosticCode.EXTERNAL_ASSET,
                    message=f"external image resource is not stored locally: {raw}",
                ),
                capabilities=AssetCapabilities(
                    replace=True,
                    open_original=True,
                    convert=True,
                    open_reference=True,
                ),
            )
        return _invalid_desktop_item(
            raw,
            DiagnosticCode.INVALID_RESOURCE_URI,
            f"invalid image resource URI: {raw}",
        )

    def _local_desktop_item(
        self,
        raw: str,
        normalized: str,
        declared: bool,
    ) -> DesktopAssetItem:
        try:
            self.relative_to_assets(normalized)
            path = self.source(normalized)
        except ValueError:
            return _invalid_desktop_item(
                raw,
                DiagnosticCode.ASSET_OUTSIDE_ASSETS,
                f"local asset is outside the configured assets directory: {raw}",
            )
        exists = path.is_file()
        diagnostic = None
        if not exists:
            diagnostic = Diagnostic(
                code=DiagnosticCode.ASSET_MISSING,
                message=f"local asset does not exist: {raw}",
            )
        return DesktopAssetItem(
            kind="local",
            reference=raw,
            display_name=Path(normalized).name,
            asset_id=stable_legacy_asset_id(raw),
            preview_path=str(path)
            if exists and path.suffix.casefold() in _IMAGE_SUFFIXES
            else None,
            exists=exists,
            declared=declared,
            diagnostic=diagnostic,
            capabilities=AssetCapabilities(
                edit=exists and path.suffix.casefold() in {".ipe", ".tex"},
                replace=exists,
                render=exists and path.suffix.casefold() == ".ipe",
                open_original=exists,
                convert=exists,
                open_reference=exists,
            ),
        )

    def _logical_desktop_item(
        self,
        manifest: AssetManifest,
        history_ids: set[str],
        *,
        declared: bool,
    ) -> DesktopAssetItem:
        renderable = [item for item in manifest.representations if item.renderable]
        capabilities = AssetCapabilities(
            edit=any(item.editable and item.path is not None for item in manifest.representations),
            replace=True,
            render=any(
                item.editable and item.format == AssetFormat.IPE and item.path is not None
                for item in manifest.representations
            ),
            set_render=len(renderable) > 1,
            open_original=any(
                item.purpose in {"original", "reference", "source-context"}
                or item.derived_from is None
                for item in manifest.representations
            ),
            show_directory=True,
            restore=manifest.asset_id in history_ids,
        )
        return DesktopAssetItem(
            kind="logical",
            reference=f"qbank-asset:{manifest.asset_id}",
            display_name=manifest.asset_id,
            asset_id=manifest.asset_id,
            manifest=manifest,
            preview_path=self._logical_preview_path(manifest),
            exists=True,
            declared=declared,
            capabilities=capabilities,
        )

    def _logical_preview_path(self, manifest: AssetManifest) -> str | None:
        preferred = [manifest.preferred_render] if manifest.preferred_render else []
        candidates = preferred + [
            item.representation_id for item in manifest.representations if item.renderable
        ]
        for representation_id in dict.fromkeys(candidates):
            path = self.registry.repository.representation_path(manifest, representation_id)
            if path is not None and path.is_file() and path.suffix.casefold() in _IMAGE_SUFFIXES:
                return str(path)
        return None

    def copy_questions(
        self,
        questions: list[Question],
        destination_root: Path,
        *,
        output_assets: Path | None = None,
        target: AssetTarget = "generic",
    ) -> list[str]:
        """Copy unique declared assets and return output-relative paths."""
        plan = self.question_copy_plan(
            questions,
            destination_root,
            output_assets=output_assets,
            target=target,
        )
        for source, destination in plan.values():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return sorted(plan)

    def question_copy_plan(
        self,
        questions: list[Question],
        destination_root: Path,
        *,
        output_assets: Path | None = None,
        target: AssetTarget = "generic",
    ) -> dict[str, tuple[Path, Path]]:
        """Return output-relative names mapped to source and destination paths."""
        output_assets = output_assets or Path(self.context.config.paths.assets)
        plan: dict[str, tuple[Path, Path]] = {}
        projected, _ = self.project_questions(questions, target=target)
        for question in projected:
            for raw in question.assets:
                reference = classify_resource_uri(raw)
                if reference.kind != AssetKind.LOCAL or reference.normalized is None:
                    continue
                relative = self.relative_to_assets(reference.normalized)
                destination = destination_root / output_assets / relative
                name = (output_assets / relative).as_posix()
                plan[name] = (self.source(reference.normalized), destination)
        return dict(sorted(plan.items()))

    def project_questions(
        self,
        questions: list[Question],
        *,
        target: AssetTarget,
        require_final: bool = False,
    ) -> tuple[list[Question], list[Diagnostic]]:
        """Replace logical/managed legacy references with selected target forms."""
        projected: list[Question] = []
        warnings: list[Diagnostic] = []
        for question in questions:
            item, item_warnings = self.project_question(
                question,
                target=target,
                require_final=require_final,
            )
            projected.append(item)
            warnings.extend(item_warnings)
        return projected, warnings

    def project_question(
        self,
        question: Question,
        *,
        target: AssetTarget,
        require_final: bool = False,
    ) -> tuple[Question, list[Diagnostic]]:
        """Project all registered references in one question deterministically."""
        projected, warnings, _ = self.project_question_with_bindings(
            question,
            target=target,
            require_final=require_final,
        )
        return projected, warnings

    def project_question_with_bindings(
        self,
        question: Question,
        *,
        target: AssetTarget,
        require_final: bool = False,
    ) -> tuple[Question, list[Diagnostic], dict[str, str]]:
        """Project one question and bind selected URIs back to stable asset IDs."""
        replacements: dict[str, str] = {}
        tex_replacements: dict[str, str] = {}
        bindings: dict[str, str] = {}
        declarations: list[str] = []
        warnings: list[Diagnostic] = []
        seen_manifests: set[str] = set()
        for raw in question.assets:
            reference = classify_resource_uri(raw)
            manifest = self._manifest_for_reference(question.id, reference, raw)
            if manifest is None:
                declarations.append(raw)
                if reference.kind in {AssetKind.LOCAL, AssetKind.EXTERNAL}:
                    bindings[raw] = stable_legacy_asset_id(raw)
                continue
            selected = self.registry.select(
                manifest,
                target,
                requested=reference.representation_id,
            )
            resolved = self._selected_uri(manifest, selected.representation_id)
            replacements[raw] = resolved
            if reference.kind == AssetKind.LOGICAL:
                suffix = (
                    f"#{reference.representation_id}"
                    if reference.representation_id is not None
                    else ""
                )
                replacements[f"asset:{manifest.asset_id}{suffix}"] = resolved
                replacements[f"qbank-asset:{manifest.asset_id}{suffix}"] = resolved
                tex_replacements[manifest.asset_id] = resolved
            bindings[resolved] = manifest.asset_id
            declarations.append(resolved)
            if manifest.asset_id not in seen_manifests:
                warnings.extend(
                    self.registry.selection_diagnostics(
                        manifest,
                        require_final=require_final,
                    )
                )
                seen_manifests.add(manifest.asset_id)
        updates: dict[str, object] = {
            "assets": list(dict.fromkeys(declarations)),
        }
        for field in QUESTION_CONTENT_FIELDS:
            markdown = replace_image_uris(
                getattr(question, field),
                replacements,
            )
            updates[field] = replace_tex_asset_references(markdown, tex_replacements)
        projected = Question.model_validate(
            {
                **question.model_dump(mode="python"),
                **updates,
            }
        )
        return projected, warnings, bindings

    def _manifest_for_reference(
        self,
        question_id: str,
        reference: AssetReference,
        raw: str,
    ) -> AssetManifest | None:
        if reference.kind == AssetKind.LOGICAL and reference.asset_id is not None:
            return self.registry.repository.get(question_id, reference.asset_id)
        if reference.kind == AssetKind.LOCAL:
            return self.registry.repository.find_by_reference(question_id, raw)
        return None

    def _selected_uri(
        self,
        manifest: AssetManifest,
        representation_id: str,
    ) -> str:
        representation = next(
            item for item in manifest.representations if item.representation_id == representation_id
        )
        if representation.url is not None:
            return representation.url
        path = self.registry.repository.representation_path(
            manifest,
            representation_id,
        )
        if path is None:
            raise RuntimeError("selected local representation has no path")
        return path.relative_to(self.context.root).as_posix()


def _default_registry(context: ProjectContext) -> AssetApplicationService:
    from qbank.infrastructure import (
        AssetInputAdapter,
        FileAssetRepository,
        IpeRenderAdapter,
        RepositoryWriteLock,
        SafeAssetLauncher,
    )

    lock = RepositoryWriteLock(context)

    return AssetApplicationService(
        repository=FileAssetRepository(context),
        inputs=AssetInputAdapter(context),
        renderer=IpeRenderAdapter(context),
        launcher=SafeAssetLauncher(context),
        lock=lock,
    )


def replace_image_uris(markdown: str, replacements: dict[str, str]) -> str:
    """Rewrite Markdown image destinations without touching rendered HTML."""
    if not replacements:
        return markdown
    pattern = re.compile(r"(!\[[^\]]*\]\()([^) \t]+)([^)]*\))")

    def replace(match: re.Match[str]) -> str:
        raw = match.group(2)
        return f"{match.group(1)}{replacements.get(raw, raw)}{match.group(3)}"

    return pattern.sub(replace, markdown)


def replace_tex_asset_references(markdown: str, replacements: dict[str, str]) -> str:
    """Render stable TeX asset commands as target-selected Markdown images."""
    if not replacements:
        return markdown
    pattern = re.compile(r"\\qbankasset\s*\{\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*\}")

    def replace(match: re.Match[str]) -> str:
        asset_id = match.group(1)
        uri = replacements.get(asset_id)
        return match.group(0) if uri is None else f"![{asset_id}]({uri})"

    return pattern.sub(replace, markdown)


def stable_legacy_asset_id(reference: str) -> str:
    """Return a deterministic pending logical ID for a legacy image URI."""
    digest = sha256(reference.strip().encode("utf-8")).hexdigest()
    return f"legacy-{digest[:12]}"


def _invalid_desktop_item(
    reference: str,
    code: DiagnosticCode,
    message: str,
    *,
    asset_id: str | None = None,
) -> DesktopAssetItem:
    return DesktopAssetItem(
        kind="invalid",
        reference=reference,
        display_name=reference,
        asset_id=asset_id,
        diagnostic=Diagnostic(code=code, message=message),
    )
