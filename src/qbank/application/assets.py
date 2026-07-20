"""Typed use cases for durable multi-representation question assets."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from qbank.application.ports import (
    AssetInputPort,
    AssetLauncherPort,
    AssetRendererPort,
    AssetRepositoryPort,
)
from qbank.domain import (
    AssetHistoryEvent,
    AssetTarget,
    NormalizedAssetInput,
    RenderedAsset,
    select_asset_representation,
)
from qbank.errors import (
    AssetCommandError,
    AssetConflictError,
    AssetNotFoundError,
    DataValidationError,
)
from qbank.models import (
    AssetCommandResult,
    AssetFormat,
    AssetListResult,
    AssetManifest,
    AssetMutationResult,
    AssetPackage,
    AssetPackageRepresentation,
    AssetRenderResult,
    AssetRepresentation,
    AssetShowResult,
    AssetStatus,
    AssetValidationReport,
    AssetValidationSummary,
    Diagnostic,
    DiagnosticCode,
)

PreferenceKind = Literal["editor", "render"]


class AssetApplicationService:
    """Orchestrate asset storage, normalization, editing, and rendering ports."""

    def __init__(
        self,
        repository: AssetRepositoryPort,
        inputs: AssetInputPort,
        renderer: AssetRendererPort,
        launcher: AssetLauncherPort,
    ):
        self.repository = repository
        self.inputs = inputs
        self.renderer = renderer
        self.launcher = launcher

    def list_assets(self, question_id: str) -> AssetListResult:
        """List all logical assets registered for one question."""
        return AssetListResult(
            ok=True,
            question_id=question_id,
            assets=list(self.repository.list(question_id)),
        )

    def show_asset(self, question_id: str, asset_id: str) -> AssetShowResult:
        """Return one full manifest and its project-relative path."""
        manifest = self.repository.get(question_id, asset_id)
        return AssetShowResult(
            ok=True,
            asset=manifest,
            manifest_path=self.repository.location(question_id, asset_id).relative_manifest,
        )

    def ingest_package(
        self,
        package: AssetPackage,
        package_root: Path,
        *,
        dry_run: bool,
        download: bool = False,
    ) -> AssetMutationResult:
        """Normalize and transactionally ingest one exchange package."""
        normalized = tuple(
            self.inputs.normalize(
                item,
                package_root=package_root,
                download=download,
            )
            for item in package.representations
        )
        existing = self._existing(package.question_id, package.asset_id)
        manifest, files, action = _merge_package(package, normalized, existing)
        location = self.repository.location(package.question_id, package.asset_id)
        result = AssetMutationResult(
            ok=True,
            dry_run=dry_run,
            action=action,
            question_id=package.question_id,
            asset_id=package.asset_id,
            manifest_path=location.relative_manifest,
            representations=[item.representation_id for item in manifest.representations],
            warnings=_lifecycle_warnings(manifest),
        )
        if dry_run or action == "unchanged":
            return result
        self.repository.commit(
            manifest,
            files,
            AssetHistoryEvent(
                operation="asset_ingest",
                question_id=manifest.question_id,
                asset_id=manifest.asset_id,
                representation_ids=tuple(files),
                changes=({"action": action},),
            ),
        )
        return result

    def replace(
        self,
        question_id: str,
        asset_id: str,
        representation: AssetPackageRepresentation,
        package_root: Path,
        *,
        dry_run: bool,
    ) -> AssetMutationResult:
        """Add a new version and select it without overwriting prior content."""
        manifest = self.repository.get(question_id, asset_id)
        normalized = self.inputs.normalize(representation, package_root=package_root)
        normalized = _versioned_replacement(normalized, manifest)
        updated = _updated_manifest(
            manifest,
            representations=[*manifest.representations, normalized.representation],
            preferred_render=(
                normalized.representation.representation_id
                if normalized.representation.renderable
                else manifest.preferred_render
            ),
            status=AssetStatus.EDITING,
        )
        result = self._mutation_result(updated, "replace", dry_run=dry_run)
        if not dry_run:
            self.repository.commit(
                updated,
                _content_files((normalized,)),
                AssetHistoryEvent(
                    operation="asset_replace",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=(normalized.representation.representation_id,),
                ),
            )
        return result

    def set_preference(
        self,
        question_id: str,
        asset_id: str,
        representation_id: str,
        *,
        kind: PreferenceKind,
        dry_run: bool,
    ) -> AssetMutationResult:
        """Select one registered editable or renderable representation."""
        manifest = self.repository.get(question_id, asset_id)
        representation = _representation(manifest, representation_id)
        if kind == "editor" and not representation.editable:
            raise DataValidationError(
                f"asset_command_rejected: representation is not editable: {representation_id}"
            )
        if kind == "render" and not representation.renderable:
            raise DataValidationError(
                f"asset_command_rejected: representation is not renderable: {representation_id}"
            )
        values = (
            {
                "preferred_editor": representation_id,
            }
            if kind == "editor"
            else {
                "preferred_render": representation_id,
            }
        )
        updated = _updated_manifest(manifest, **values)
        action: Literal["set_editor", "set_render"] = (
            "set_editor" if kind == "editor" else "set_render"
        )
        result = self._mutation_result(updated, action, dry_run=dry_run)
        if not dry_run:
            self.repository.commit(
                updated,
                {},
                AssetHistoryEvent(
                    operation=f"asset_{action}",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=(representation_id,),
                ),
            )
        return result

    def finalize(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetMutationResult:
        """Mark a validated asset final without changing any representation."""
        manifest = self.repository.get(question_id, asset_id)
        selected = self.select(manifest, "generic")
        path = self.repository.representation_path(manifest, selected.representation_id)
        if path is not None and not path.is_file():
            raise DataValidationError(
                f"asset_representation_missing: preferred render does not exist: {path}"
            )
        updated = _updated_manifest(manifest, status=AssetStatus.FINAL)
        result = self._mutation_result(updated, "finalize", dry_run=dry_run)
        if not dry_run:
            self.repository.commit(
                updated,
                {},
                AssetHistoryEvent(
                    operation="asset_finalize",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=(selected.representation_id,),
                ),
            )
        return result

    def open_asset(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetCommandResult:
        """Open the selected preview using only a registered representation."""
        manifest = self.repository.get(question_id, asset_id)
        representation = self.select(manifest, "preview")
        return self._launch(manifest, representation, "open", dry_run=dry_run)

    def edit_asset(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetCommandResult:
        """Open the selected editable representation with a built-in adapter."""
        manifest = self.repository.get(question_id, asset_id)
        representation = _editor_representation(manifest)
        result = self._launch(manifest, representation, "edit", dry_run=dry_run)
        if not dry_run and manifest.status != AssetStatus.EDITING:
            updated = _updated_manifest(manifest, status=AssetStatus.EDITING)
            self.repository.commit(
                updated,
                {},
                AssetHistoryEvent(
                    operation="asset_edit",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=(representation.representation_id,),
                ),
            )
        return result

    def open_asset_directory(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetCommandResult:
        """Open only the containment-checked directory of a registered asset."""
        self.repository.get(question_id, asset_id)
        directory = self.repository.location(question_id, asset_id).directory
        command = self.launcher.open_directory(directory, execute=not dry_run)
        if not dry_run:
            self.repository.record(
                AssetHistoryEvent(
                    operation="asset_open_directory",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=(),
                )
            )
        return AssetCommandResult(
            ok=True,
            dry_run=dry_run,
            action="open_directory",
            question_id=question_id,
            asset_id=asset_id,
            representation_id="",
            target=str(directory),
            command=list(command),
        )

    def render_asset(
        self,
        question_id: str,
        asset_id: str,
        *,
        formats: Sequence[AssetFormat],
        dry_run: bool,
    ) -> AssetRenderResult:
        """Render an Ipe source to immutable hash-versioned derivatives."""
        manifest = self.repository.get(question_id, asset_id)
        source = _ipe_source(manifest)
        path = self.repository.representation_path(manifest, source.representation_id)
        if path is None or not path.is_file():
            raise DataValidationError(
                f"asset_representation_missing: editable Ipe source is missing: {source.path}"
            )
        try:
            rendered = self.renderer.render(path, formats, execute=not dry_run)
        except AssetCommandError:
            if not dry_run:
                self._record_render_failure(manifest, source)
            raise
        if dry_run:
            return self._render_result(
                manifest,
                source,
                rendered,
                generated=[f"render-{item.format.value}" for item in rendered],
                dry_run=True,
            )
        updated, files, generated = _merge_rendered(manifest, source, rendered)
        self.repository.commit(
            updated,
            files,
            AssetHistoryEvent(
                operation="asset_render",
                question_id=question_id,
                asset_id=asset_id,
                representation_ids=tuple(generated),
            ),
        )
        return self._render_result(
            updated,
            source,
            rendered,
            generated=generated,
            dry_run=False,
        )

    def validate_assets(
        self,
        *,
        known_question_ids: set[str] | None = None,
    ) -> AssetValidationReport:
        """Validate every manifest, stored file, hash, lifecycle, and owner."""
        issues = list(self.repository.diagnostics())
        manifests = self.repository.list(strict=False)
        for manifest in manifests:
            issues.extend(self._manifest_issues(manifest, known_question_ids))
        errors = sum(item.severity == "error" for item in issues)
        warnings = sum(item.severity == "warning" for item in issues)
        return AssetValidationReport(
            ok=errors == 0,
            summary=AssetValidationSummary(
                assets=len(manifests),
                representations=sum(len(item.representations) for item in manifests),
                errors=errors,
                warnings=warnings,
            ),
            issues=issues,
        )

    def select(
        self,
        manifest: AssetManifest,
        target: AssetTarget,
        *,
        requested: str | None = None,
    ) -> AssetRepresentation:
        """Select a target-compatible representation or raise a stable error."""
        representation = select_asset_representation(manifest, target, requested=requested)
        if representation is None:
            suffix = f" ({requested})" if requested else ""
            raise DataValidationError(
                "asset_representation_missing: no compatible representation "
                f"for {manifest.question_id}/{manifest.asset_id}{suffix}"
            )
        return representation

    def selection_diagnostics(
        self,
        manifest: AssetManifest,
        *,
        require_final: bool = False,
    ) -> list[Diagnostic]:
        """Return deterministic lifecycle diagnostics for paper/export selection."""
        if manifest.status == AssetStatus.FINAL:
            return []
        severity: Literal["error", "warning"] = "error" if require_final else "warning"
        code = (
            DiagnosticCode.ASSET_FAILED
            if manifest.status == AssetStatus.FAILED
            else DiagnosticCode.ASSET_NEEDS_REDRAW
        )
        return [
            Diagnostic(
                severity=severity,
                code=code,
                id=manifest.question_id,
                field="assets",
                message=(
                    f"asset {manifest.asset_id} is {manifest.status.value}; "
                    "final paper output should use reviewed or final assets"
                ),
            )
        ]

    def _existing(self, question_id: str, asset_id: str) -> AssetManifest | None:
        try:
            return self.repository.get(question_id, asset_id)
        except AssetNotFoundError:
            return None

    def _mutation_result(
        self,
        manifest: AssetManifest,
        action: Literal[
            "replace",
            "set_render",
            "set_editor",
            "finalize",
            "normalize",
        ],
        *,
        dry_run: bool,
    ) -> AssetMutationResult:
        return AssetMutationResult(
            ok=True,
            dry_run=dry_run,
            action=action,
            question_id=manifest.question_id,
            asset_id=manifest.asset_id,
            manifest_path=self.repository.location(
                manifest.question_id,
                manifest.asset_id,
            ).relative_manifest,
            representations=[item.representation_id for item in manifest.representations],
            warnings=_lifecycle_warnings(manifest),
        )

    def _launch(
        self,
        manifest: AssetManifest,
        representation: AssetRepresentation,
        action: Literal["open", "edit"],
        *,
        dry_run: bool,
    ) -> AssetCommandResult:
        path = self.repository.representation_path(
            manifest,
            representation.representation_id,
        )
        if representation.url is not None:
            command = self.launcher.open_url(representation.url, execute=not dry_run)
            target = representation.url
        elif path is not None and path.is_file():
            command = (
                self.launcher.edit_file(path, representation.format, execute=not dry_run)
                if action == "edit"
                else self.launcher.open_file(path, execute=not dry_run)
            )
            target = str(path)
        else:
            raise DataValidationError(
                f"asset_representation_missing: representation is missing: {representation.path}"
            )
        if not dry_run and action == "open":
            self.repository.record(
                AssetHistoryEvent(
                    operation="asset_open",
                    question_id=manifest.question_id,
                    asset_id=manifest.asset_id,
                    representation_ids=(representation.representation_id,),
                )
            )
        return AssetCommandResult(
            ok=True,
            dry_run=dry_run,
            action=action,
            question_id=manifest.question_id,
            asset_id=manifest.asset_id,
            representation_id=representation.representation_id,
            target=target,
            command=list(command),
        )

    def _record_render_failure(
        self,
        manifest: AssetManifest,
        source: AssetRepresentation,
    ) -> None:
        failed = _updated_manifest(manifest, status=AssetStatus.FAILED)
        self.repository.commit(
            failed,
            {},
            AssetHistoryEvent(
                operation="asset_render_failed",
                question_id=manifest.question_id,
                asset_id=manifest.asset_id,
                representation_ids=(source.representation_id,),
            ),
        )

    def _render_result(
        self,
        manifest: AssetManifest,
        source: AssetRepresentation,
        rendered: Sequence[RenderedAsset],
        *,
        generated: list[str],
        dry_run: bool,
    ) -> AssetRenderResult:
        commands = [list(item.command) for item in rendered if hasattr(item, "command")]
        return AssetRenderResult(
            ok=True,
            dry_run=dry_run,
            question_id=manifest.question_id,
            asset_id=manifest.asset_id,
            manifest_path=self.repository.location(
                manifest.question_id,
                manifest.asset_id,
            ).relative_manifest,
            representations=[item.representation_id for item in manifest.representations],
            generated=generated,
            commands=commands,
            warnings=_lifecycle_warnings(manifest),
        )

    def _manifest_issues(
        self,
        manifest: AssetManifest,
        known_question_ids: set[str] | None,
    ) -> list[Diagnostic]:
        issues = _lifecycle_warnings(manifest)
        if known_question_ids is not None and manifest.question_id not in known_question_ids:
            issues.append(
                Diagnostic(
                    code=DiagnosticCode.MISSING_QUESTION,
                    id=manifest.question_id,
                    message=f"asset owner question does not exist: {manifest.question_id}",
                )
            )
        for representation in manifest.representations:
            issues.extend(self._representation_issues(manifest, representation))
        return issues

    def _representation_issues(
        self,
        manifest: AssetManifest,
        representation: AssetRepresentation,
    ) -> list[Diagnostic]:
        path = self.repository.representation_path(manifest, representation.representation_id)
        if path is None:
            return []
        if not path.is_file():
            return [
                Diagnostic(
                    code=DiagnosticCode.ASSET_REPRESENTATION_MISSING,
                    id=manifest.question_id,
                    field=representation.representation_id,
                    message=f"asset representation does not exist: {path}",
                )
            ]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == representation.content_hash:
            return []
        return [
            Diagnostic(
                code=DiagnosticCode.ASSET_HASH_MISMATCH,
                id=manifest.question_id,
                field=representation.representation_id,
                message=f"asset representation hash does not match: {path}",
            )
        ]


def _merge_package(
    package: AssetPackage,
    normalized: tuple[NormalizedAssetInput, ...],
    existing: AssetManifest | None,
) -> tuple[AssetManifest, dict[str, bytes], Literal["create", "update", "unchanged"]]:
    if existing is None:
        manifest = AssetManifest(
            schema_version=package.schema_version,
            asset_id=package.asset_id,
            question_id=package.question_id,
            role=package.role,
            status=package.status,
            preferred_editor=package.suggested_editor,
            preferred_render=package.suggested_render,
            representations=[item.representation for item in normalized],
            provenance=package.provenance,
            review_notes=package.review_notes,
        )
        return manifest, _content_files(normalized), "create"
    additions = _new_package_representations(existing, normalized)
    manifest = _updated_manifest(
        existing,
        role=package.role,
        status=package.status,
        preferred_editor=package.suggested_editor or existing.preferred_editor,
        preferred_render=package.suggested_render or existing.preferred_render,
        representations=[*existing.representations, *[item.representation for item in additions]],
        provenance=package.provenance,
        review_notes=package.review_notes,
    )
    action: Literal["update", "unchanged"] = "unchanged" if manifest == existing else "update"
    return manifest, _content_files(additions), action


def _new_package_representations(
    existing: AssetManifest,
    normalized: tuple[NormalizedAssetInput, ...],
) -> tuple[NormalizedAssetInput, ...]:
    by_id = {item.representation_id: item for item in existing.representations}
    additions: list[NormalizedAssetInput] = []
    for item in normalized:
        previous = by_id.get(item.representation.representation_id)
        if previous is None:
            additions.append(item)
        elif previous != item.representation:
            raise AssetConflictError(
                "asset_conflict: representation ID already contains different content: "
                f"{item.representation.representation_id}"
            )
    return tuple(additions)


def _updated_manifest(manifest: AssetManifest, **changes: object) -> AssetManifest:
    values = manifest.model_dump(mode="python")
    values.update(changes)
    return AssetManifest.model_validate(values)


def _content_files(
    normalized: Sequence[NormalizedAssetInput],
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for item in normalized:
        path = item.representation.path
        content = item.content
        if path is not None and content is not None:
            files[path] = content
    return files


def _versioned_replacement(
    normalized: NormalizedAssetInput,
    manifest: AssetManifest,
) -> NormalizedAssetInput:
    representation = normalized.representation
    if representation.content_hash is None:
        return normalized
    base = representation.representation_id
    identifier = f"{base}-{representation.content_hash[:8]}"
    if any(item.representation_id == identifier for item in manifest.representations):
        raise AssetConflictError(f"asset_conflict: replacement already exists: {identifier}")
    suffix = PureSuffix.from_path(representation.path)
    updated = AssetRepresentation.model_validate(
        {
            **representation.model_dump(mode="python"),
            "representation_id": identifier,
            "path": f"{identifier}{suffix}",
            "derived_from": representation.derived_from or manifest.preferred_render,
        }
    )
    return NormalizedAssetInput(representation=updated, content=normalized.content)


class PureSuffix:
    """Small path-suffix helper that never interprets an absolute path."""

    @staticmethod
    def from_path(path: str | None) -> str:
        if path is None:
            return ""
        return Path(path).suffix.lower()


def _representation(
    manifest: AssetManifest,
    representation_id: str,
) -> AssetRepresentation:
    for representation in manifest.representations:
        if representation.representation_id == representation_id:
            return representation
    raise AssetNotFoundError(
        "asset_not_found: representation does not exist: "
        f"{manifest.question_id}/{manifest.asset_id}/{representation_id}"
    )


def _editor_representation(manifest: AssetManifest) -> AssetRepresentation:
    if manifest.preferred_editor is not None:
        return _representation(manifest, manifest.preferred_editor)
    editable = [item for item in manifest.representations if item.editable]
    if not editable:
        raise DataValidationError(
            f"asset_command_rejected: asset has no editable representation: {manifest.asset_id}"
        )
    return min(
        editable,
        key=lambda item: (
            0 if item.format == AssetFormat.IPE else 1,
            item.representation_id,
        ),
    )


def _ipe_source(manifest: AssetManifest) -> AssetRepresentation:
    editor = _editor_representation(manifest)
    if editor.format == AssetFormat.IPE:
        return editor
    for representation in manifest.representations:
        if representation.format == AssetFormat.IPE and representation.editable:
            return representation
    raise DataValidationError(
        f"asset_command_rejected: asset has no editable Ipe source: {manifest.asset_id}"
    )


def _merge_rendered(
    manifest: AssetManifest,
    source: AssetRepresentation,
    rendered: Sequence[RenderedAsset],
) -> tuple[AssetManifest, dict[str, bytes], list[str]]:
    representations = list(manifest.representations)
    files: dict[str, bytes] = {}
    generated: list[str] = []
    known_hashes = {
        item.content_hash: item.representation_id
        for item in representations
        if item.content_hash is not None
    }
    for value in rendered:
        content = value.content
        format_ = value.format
        digest = hashlib.sha256(content).hexdigest()
        existing_id = known_hashes.get(digest)
        if existing_id is not None:
            generated.append(existing_id)
            continue
        identifier = f"render-{format_.value}-{digest[:8]}"
        filename = f"{identifier}.{_extension(format_)}"
        representation = AssetRepresentation(
            representation_id=identifier,
            format=format_,
            path=filename,
            purpose="render",
            editable=False,
            derived_from=source.representation_id,
            content_hash=digest,
            metadata=value.metadata,
        )
        representations.append(representation)
        files[filename] = content
        generated.append(identifier)
        known_hashes[digest] = identifier
    preferred = manifest.preferred_render or (generated[0] if generated else None)
    updated = _updated_manifest(
        manifest,
        representations=representations,
        preferred_render=preferred,
        status=AssetStatus.EDITING,
    )
    return updated, files, generated


def _extension(format_: AssetFormat) -> str:
    return "jpg" if format_ == AssetFormat.JPEG else format_.value


def _lifecycle_warnings(manifest: AssetManifest) -> list[Diagnostic]:
    if manifest.status not in {
        AssetStatus.NEEDS_REDRAW,
        AssetStatus.RAW,
        AssetStatus.EDITING,
        AssetStatus.FAILED,
    }:
        return []
    code = (
        DiagnosticCode.ASSET_FAILED
        if manifest.status == AssetStatus.FAILED
        else DiagnosticCode.ASSET_NEEDS_REDRAW
    )
    severity: Literal["error", "warning"] = (
        "error" if manifest.status == AssetStatus.FAILED else "warning"
    )
    return [
        Diagnostic(
            severity=severity,
            code=code,
            id=manifest.question_id,
            field="assets",
            message=f"asset {manifest.asset_id} is {manifest.status.value}",
        )
    ]
