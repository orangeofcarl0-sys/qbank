"""Typed use cases for durable multi-representation question assets."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from qbank.application.asset_edits import (
    edit_command_result,
    edit_working_copy,
    reconciled_editor_manifest,
    restored_manifest,
)
from qbank.application.asset_manifest import (
    content_files,
    editor_representation,
    find_representation,
    ipe_source,
    lifecycle_warnings,
    merge_package,
    updated_manifest,
    versioned_replacement,
)
from qbank.application.asset_render import merge_rendered
from qbank.application.locking import RepositoryWriteLockPort
from qbank.application.ports import (
    AssetInputPort,
    AssetLauncherPort,
    AssetRendererPort,
    AssetRepositoryPort,
)
from qbank.domain import (
    AssetHistoryEvent,
    AssetTarget,
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
    AssetHistoryResult,
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
        lock: RepositoryWriteLockPort | None = None,
    ):
        self.repository = repository
        self.inputs = inputs
        self.renderer = renderer
        self.launcher = launcher
        self.lock = lock

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

    def history(
        self,
        question_id: str,
        asset_id: str | None = None,
    ) -> AssetHistoryResult:
        """Return append-only events through the registered repository port."""
        return AssetHistoryResult(
            ok=True,
            question_id=question_id,
            asset_id=asset_id,
            events=list(self.repository.history(question_id, asset_id)),
        )

    def discard_new_asset(self, question_id: str, asset_id: str) -> None:
        """Compensate a failed question declaration for a newly created asset."""
        if self.lock is None:
            self.repository.discard_new(question_id, asset_id)
            return
        with self.lock.hold("asset_discard_new"):
            self.repository.discard_new(question_id, asset_id)

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
        manifest, files, action = merge_package(package, normalized, existing)
        location = self.repository.location(package.question_id, package.asset_id)
        result = AssetMutationResult(
            ok=True,
            dry_run=dry_run,
            action=action,
            question_id=package.question_id,
            asset_id=package.asset_id,
            manifest_path=location.relative_manifest,
            representations=[item.representation_id for item in manifest.representations],
            warnings=lifecycle_warnings(manifest),
        )
        if dry_run or action == "unchanged":
            return result
        self._commit_manifest(
            existing,
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
        normalized = versioned_replacement(normalized, manifest)
        updated = updated_manifest(
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
            self._commit_manifest(
                manifest,
                updated,
                content_files((normalized,)),
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
        representation = find_representation(manifest, representation_id)
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
        updated = updated_manifest(manifest, **values)
        action: Literal["set_editor", "set_render"] = (
            "set_editor" if kind == "editor" else "set_render"
        )
        result = self._mutation_result(updated, action, dry_run=dry_run)
        if not dry_run:
            self._commit_manifest(
                manifest,
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

    def set_status(
        self,
        question_id: str,
        asset_id: str,
        status: AssetStatus,
        *,
        dry_run: bool,
    ) -> AssetMutationResult:
        """Set one lifecycle state without launching an editor or renderer."""
        manifest = self.repository.get(question_id, asset_id)
        updated = updated_manifest(manifest, status=status)
        result = self._mutation_result(updated, "set_status", dry_run=dry_run)
        if not dry_run and updated != manifest:
            self._commit_manifest(
                manifest,
                updated,
                {},
                AssetHistoryEvent(
                    operation="asset_set_status",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=(),
                    changes=({"before": manifest.status.value, "after": status.value},),
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
        updated = updated_manifest(manifest, status=AssetStatus.FINAL)
        result = self._mutation_result(updated, "finalize", dry_run=dry_run)
        if not dry_run:
            self._commit_manifest(
                manifest,
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

    def open_original(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetCommandResult:
        """Open the earliest registered original/reference representation."""
        manifest = self.repository.get(question_id, asset_id)
        candidates = [
            item
            for item in manifest.representations
            if item.purpose in {"original", "reference", "source-context"}
            or item.derived_from is None
        ]
        if not candidates:
            raise DataValidationError(
                f"asset_representation_missing: asset has no original reference: {asset_id}"
            )
        representation = min(
            candidates,
            key=lambda item: (
                0 if item.purpose == "original" else 1,
                item.representation_id,
            ),
        )
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
        representation = editor_representation(manifest)
        result = self._launch(manifest, representation, "edit", dry_run=dry_run)
        if not dry_run and manifest.status != AssetStatus.EDITING:
            updated = updated_manifest(manifest, status=AssetStatus.EDITING)
            self._commit_manifest(
                manifest,
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

    def begin_edit_session(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetCommandResult:
        """Create and open a versioned editable working copy."""
        manifest = self.repository.get(question_id, asset_id)
        editor = editor_representation(manifest)
        source = self.repository.representation_path(manifest, editor.representation_id)
        if source is None or not source.is_file():
            raise DataValidationError(
                f"asset_representation_missing: editable source is missing: {editor.path}"
            )
        if dry_run:
            command = self.launcher.edit_file(source, editor.format, execute=False)
            return edit_command_result(manifest, editor, source, command, dry_run=True)
        content = source.read_bytes()
        updated, working = edit_working_copy(manifest, editor, content)
        self._commit_manifest(
            manifest,
            updated,
            {working.path or "": content},
            AssetHistoryEvent(
                operation="asset_edit_begin",
                question_id=question_id,
                asset_id=asset_id,
                representation_ids=(working.representation_id,),
                changes=(
                    {
                        "from": editor.representation_id,
                        "to": working.representation_id,
                    },
                ),
            ),
        )
        target = self.repository.representation_path(updated, working.representation_id)
        if target is None:
            raise DataValidationError("asset_representation_missing: working copy has no path")
        command = self.launcher.edit_file(target, working.format, execute=True)
        return edit_command_result(updated, working, target, command, dry_run=False)

    def reconcile_editor_change(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetMutationResult:
        """Re-hash a saved working copy and mark previous renders stale."""
        manifest = self.repository.get(question_id, asset_id)
        editor = editor_representation(manifest)
        path = self.repository.representation_path(manifest, editor.representation_id)
        if path is None or not path.is_file():
            raise DataValidationError(
                f"asset_representation_missing: editable source is missing: {editor.path}"
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == editor.content_hash:
            return self._mutation_result(manifest, "reconcile", dry_run=dry_run)
        updated = reconciled_editor_manifest(manifest, editor, digest)
        result = self._mutation_result(updated, "reconcile", dry_run=dry_run)
        if not dry_run:
            self._commit_manifest(
                manifest,
                updated,
                {},
                AssetHistoryEvent(
                    operation="asset_edit_saved",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=(editor.representation_id,),
                    changes=(
                        {
                            "before_hash": editor.content_hash,
                            "after_hash": digest,
                            "renders_stale": True,
                        },
                    ),
                ),
            )
        return result

    def restore_previous(
        self,
        question_id: str,
        asset_id: str,
        *,
        dry_run: bool,
    ) -> AssetMutationResult:
        """Restore previous editor/render preferences without deleting versions."""
        manifest = self.repository.get(question_id, asset_id)
        updated, changes = restored_manifest(manifest)
        result = self._mutation_result(updated, "restore", dry_run=dry_run)
        if not dry_run:
            self._commit_manifest(
                manifest,
                updated,
                {},
                AssetHistoryEvent(
                    operation="asset_restore",
                    question_id=question_id,
                    asset_id=asset_id,
                    representation_ids=tuple(
                        value for value in changes.values() if isinstance(value, str)
                    ),
                    changes=(changes,),
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
            self._record_event(
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
        source = ipe_source(manifest)
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
        updated, files, generated = merge_rendered(manifest, source, rendered)
        self._commit_manifest(
            manifest,
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

    def _commit_manifest(
        self,
        expected: AssetManifest | None,
        manifest: AssetManifest,
        files: dict[str, bytes],
        event: AssetHistoryEvent,
    ) -> None:
        if self.lock is None:
            self._commit_manifest_unlocked(expected, manifest, files, event)
            return
        with self.lock.hold(event.operation):
            self._commit_manifest_unlocked(expected, manifest, files, event)

    def _commit_manifest_unlocked(
        self,
        expected: AssetManifest | None,
        manifest: AssetManifest,
        files: dict[str, bytes],
        event: AssetHistoryEvent,
    ) -> None:
        current = self._existing(manifest.question_id, manifest.asset_id)
        if current != expected:
            raise AssetConflictError(
                "asset_conflict: asset changed before the protected commit: "
                f"{manifest.question_id}/{manifest.asset_id}"
            )
        self.repository.commit(manifest, files, event)

    def _record_event(self, event: AssetHistoryEvent) -> None:
        if self.lock is None:
            self.repository.record(event)
            return
        with self.lock.hold(event.operation):
            self.repository.record(event)

    def _mutation_result(
        self,
        manifest: AssetManifest,
        action: Literal[
            "replace",
            "set_render",
            "set_editor",
            "set_status",
            "finalize",
            "normalize",
            "reconcile",
            "restore",
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
            warnings=lifecycle_warnings(manifest),
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
            self._record_event(
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
        failed = updated_manifest(manifest, status=AssetStatus.FAILED)
        self._commit_manifest(
            manifest,
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
            warnings=lifecycle_warnings(manifest),
        )

    def _manifest_issues(
        self,
        manifest: AssetManifest,
        known_question_ids: set[str] | None,
    ) -> list[Diagnostic]:
        issues = lifecycle_warnings(manifest)
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

