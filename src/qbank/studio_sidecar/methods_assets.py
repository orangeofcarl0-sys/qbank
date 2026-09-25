"""Studio Protocol logical-asset methods."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
from pathlib import Path
from typing import Any, cast

from qbank.application.revision import (
    repository_revision,
)
from qbank.asset_references import classify_resource_uri
from qbank.assets import AssetService, stable_legacy_asset_id
from qbank.markdown_codec import parse_question_text, render_question
from qbank.models import (
    AssetFormat,
    DesktopAssetItem,
)
from qbank.studio_sidecar.errors import (
    CONFLICT,
    INVALID_PARAMS,
    RpcError,
)
from qbank.studio_sidecar.session import (
    AssetEditGuard,
    OpenRepository,
    StudioSession,
    asset_package,
    asset_representation,
    authoritative_file_snapshot,
    optional_string,
    question_patch,
    required_string,
)


class AssetMethods(StudioSession):
    """Logical-asset Protocol methods."""

    def asset_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        question_id = required_string(params, "questionId")
        question = opened.snapshot.locate(question_id).question
        manifests = opened.services.assets.list_assets(question_id).assets
        history = opened.services.assets.history(question_id).events
        inventory = AssetService(opened.context, opened.services.assets)
        return [
            self._asset_item(opened, item)
            for item in inventory.desktop_items(question, manifests, history)
        ]

    def asset_open(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = required_string(params, "questionId")
        reference = optional_string(params, "reference", default="")
        if reference:
            return self._open_asset_reference(opened, question_id, reference, params)
        asset_id = required_string(params, "assetId")
        action = optional_string(params, "action", default="open")
        actions = {
            "open": opened.services.assets.open_asset,
            "original": opened.services.assets.open_original,
            "edit_ipe": opened.services.assets.begin_edit_session,
            "reveal": opened.services.assets.open_asset_directory,
        }
        handler = actions.get(action)
        if handler is None:
            raise RpcError(INVALID_PARAMS, f"unsupported asset open action: {action}")
        if action == "edit_ipe":
            self._require_current_revision(params, opened)
        dry_run = handler(question_id, asset_id, dry_run=True)
        result = handler(question_id, asset_id, dry_run=False)
        revision = self._refresh_revision(opened)
        if action == "edit_ipe":
            self._record_asset_edit_guard(opened, question_id, asset_id, revision)
        return {
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def asset_create(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = required_string(params, "questionId")
        asset_id = required_string(params, "assetId")
        source = required_string(params, "source", allow_empty=True)
        package = asset_package(params, question_id, asset_id)
        dry_asset = opened.services.assets.ingest_package(
            package, opened.context.root, dry_run=True
        )
        candidate, _, _ = parse_question_text(source)
        previous = opened.snapshot.locate(question_id).question
        reference = f"qbank-asset:{asset_id}"
        if reference not in candidate.assets:
            candidate = candidate.model_copy(update={"assets": [*candidate.assets, reference]})
        patch = question_patch(previous, candidate)
        committed = opened.services.assets.ingest_package(
            package, opened.context.root, dry_run=False
        )
        try:
            validation = self._validate_source(question_id, render_question(candidate))
            if not validation["ok"]:
                opened.services.assets.discard_new_asset(question_id, asset_id)
                return {
                    "ok": False,
                    "validation": validation,
                    "asset": dry_asset.model_dump(mode="json"),
                }
            dry_question = opened.services.studio.save_question(
                question_id,
                patch,
                dry_run=True,
                command="qbank studio protocol asset create",
            )
            if not dry_question.ok:
                opened.services.assets.discard_new_asset(question_id, asset_id)
                return {
                    "ok": False,
                    "asset": dry_asset.model_dump(mode="json"),
                    "question": dry_question.model_dump(mode="json"),
                }
            saved = opened.services.studio.save_question(
                question_id,
                patch,
                dry_run=False,
                command="qbank studio protocol asset create",
            )
        except Exception as original:
            try:
                opened.services.assets.discard_new_asset(question_id, asset_id)
            except Exception as rollback:
                original.add_note(f"asset compensation failed: {rollback}")
            raise
        return {
            "ok": saved.ok,
            "asset": committed.model_dump(mode="json"),
            "question": saved.model_dump(mode="json"),
            "reference": reference,
            "revision": self._refresh_snapshot(opened),
        }

    def asset_replace(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = required_string(params, "questionId")
        asset_id = required_string(params, "assetId")
        representation = asset_representation(params, "replacement")
        dry_run = opened.services.assets.replace(
            question_id,
            asset_id,
            representation,
            opened.context.root,
            dry_run=True,
        )
        result = opened.services.assets.replace(
            question_id,
            asset_id,
            representation,
            opened.context.root,
            dry_run=False,
        )
        return {
            "dryRun": dry_run.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "revision": self._refresh_revision(opened),
        }

    def asset_render(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = required_string(params, "questionId")
        asset_id = required_string(params, "assetId")
        raw_formats_value: object = params.get("formats", ["svg", "png", "pdf"])
        if not isinstance(raw_formats_value, list):
            raise RpcError(INVALID_PARAMS, "formats must be an array of strings")
        format_items = cast(list[object], raw_formats_value)
        if not all(isinstance(item, str) for item in format_items):
            raise RpcError(INVALID_PARAMS, "formats must be an array of strings")
        raw_formats = cast(list[str], format_items)
        formats = [AssetFormat(item) for item in raw_formats]
        dry_run = opened.services.assets.render_asset(
            question_id, asset_id, formats=formats, dry_run=True
        )
        result = opened.services.assets.render_asset(
            question_id, asset_id, formats=formats, dry_run=False
        )
        revision = self._refresh_revision(opened)
        self._record_asset_edit_guard(opened, question_id, asset_id, revision)
        return {
            "dryRun": dry_run.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "assets": self.asset_list({"questionId": question_id}),
            "revision": revision,
        }

    def asset_reconcile(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = required_string(params, "questionId")
        asset_id = required_string(params, "assetId")
        self._require_reconcile_revision(params, opened, question_id, asset_id)
        before = opened.services.assets.show_asset(question_id, asset_id).asset
        dry_run = opened.services.assets.reconcile_editor_change(
            question_id, asset_id, dry_run=True
        )
        reconciled = opened.services.assets.reconcile_editor_change(
            question_id, asset_id, dry_run=False
        )
        after = opened.services.assets.show_asset(question_id, asset_id).asset
        changed = before != after
        render: dict[str, Any] | None = None
        if changed:
            render = self.asset_render(
                {
                    "questionId": question_id,
                    "assetId": asset_id,
                    "formats": ["svg", "png", "pdf"],
                    "expectedRevision": self._refresh_revision(opened),
                }
            )
        return {
            "changed": changed,
            "dryRun": dry_run.model_dump(mode="json"),
            "reconciled": reconciled.model_dump(mode="json"),
            "render": render,
            "revision": self._refresh_revision(opened),
        }

    def _open_asset_reference(
        self,
        opened: OpenRepository,
        question_id: str,
        reference: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        action = optional_string(params, "action", default="open_reference")
        if action not in {"open_reference", "reveal_reference"}:
            raise RpcError(INVALID_PARAMS, f"unsupported resource open action: {action}")
        question = opened.snapshot.locate(question_id).question
        manifests = opened.services.assets.list_assets(question_id).assets
        history = opened.services.assets.history(question_id).events
        inventory = AssetService(opened.context, opened.services.assets)
        item = next(
            (
                candidate
                for candidate in inventory.desktop_items(question, manifests, history)
                if candidate.reference == reference
            ),
            None,
        )
        if item is None or not item.capabilities.open_reference:
            raise RpcError(INVALID_PARAMS, "resource is not an openable member of this question")
        classified = classify_resource_uri(reference)
        if item.kind == "local" and classified.normalized is not None:
            path = inventory.source(classified.normalized)
            inventory.relative_to_assets(classified.normalized)
            if action == "reveal_reference":
                dry_run = opened.services.assets.launcher.open_directory(path.parent, execute=False)
                result = opened.services.assets.launcher.open_directory(path.parent, execute=True)
            else:
                dry_run = opened.services.assets.launcher.open_file(path, execute=False)
                result = opened.services.assets.launcher.open_file(path, execute=True)
        elif item.kind == "external" and action == "open_reference":
            url = f"https:{reference}" if reference.startswith("//") else reference
            dry_run = opened.services.assets.launcher.open_url(url, execute=False)
            result = opened.services.assets.launcher.open_url(url, execute=True)
        else:
            raise RpcError(
                INVALID_PARAMS, "resource action is not supported for this resource kind"
            )
        return {
            "dryRun": {"command": list(dry_run)},
            "result": {"command": list(result)},
            "revision": self._refresh_revision(opened),
        }

    def _asset_item(self, opened: OpenRepository, item: DesktopAssetItem) -> dict[str, Any]:
        manifest = item.manifest
        preferred = manifest.preferred_render if manifest is not None else None
        has_ipe = manifest is not None and any(
            representation.format == AssetFormat.IPE and representation.editable
            for representation in manifest.representations
        )
        preview_data_url = self._preview_data_url(opened, item.preview_path)
        diagnostic = (
            item.diagnostic.model_dump(mode="json", exclude_none=True)
            if item.diagnostic is not None
            else None
        )
        return {
            "assetId": item.asset_id or stable_legacy_asset_id(item.reference),
            "kind": item.kind,
            "reference": item.reference,
            "displayName": item.display_name,
            "declared": item.declared,
            "exists": item.exists,
            "diagnostic": diagnostic,
            "role": manifest.role if manifest is not None else "figure",
            "status": manifest.status.value if manifest is not None else item.kind,
            "preferredRepresentation": preferred,
            "previewDataUrl": preview_data_url,
            "capabilities": {
                "canEditIpe": has_ipe,
                "canReplace": item.kind == "logical" and item.capabilities.replace,
                "canOpen": item.capabilities.open_original or item.capabilities.open_reference,
                "canRender": item.kind == "logical" and item.capabilities.render,
                "canReveal": (item.kind == "logical" and item.capabilities.show_directory)
                or (item.kind == "local" and item.capabilities.open_reference),
            },
            "representations": [
                {
                    "representationId": representation.representation_id,
                    "format": representation.format.value,
                    "stale": representation.stale,
                    "editable": representation.editable,
                    "renderable": representation.renderable,
                }
                for representation in (manifest.representations if manifest is not None else [])
            ],
        }

    @staticmethod
    def _preview_data_url(opened: OpenRepository, raw_path: str | None) -> str | None:
        if raw_path is None:
            return None
        try:
            path = Path(raw_path).resolve(strict=True)
            path.relative_to(opened.context.paths.assets.resolve(strict=True))
        except (OSError, ValueError):
            return None
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            return None
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return f"data:{media_type};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    def _record_asset_edit_guard(
        self,
        opened: OpenRepository,
        question_id: str,
        asset_id: str,
        revision: str,
    ) -> None:
        manifest = opened.services.assets.show_asset(question_id, asset_id).asset
        editor = next(
            (
                item
                for item in manifest.representations
                if item.format == AssetFormat.IPE and item.editable
            ),
            None,
        )
        if editor is None:
            return
        source = opened.services.assets.repository.representation_path(
            manifest,
            editor.representation_id,
        )
        if source is None or not source.is_file():
            return
        resolved = source.resolve(strict=True)
        self._asset_edit_guards[(question_id, asset_id)] = AssetEditGuard(
            revision=revision,
            source=resolved,
            source_hash=hashlib.sha256(resolved.read_bytes()).hexdigest(),
            other_files=authoritative_file_snapshot(opened.context, exclude=resolved),
        )

    def _require_reconcile_revision(
        self,
        params: dict[str, Any],
        opened: OpenRepository,
        question_id: str,
        asset_id: str,
    ) -> str:
        expected = required_string(params, "expectedRevision")
        current = repository_revision(opened.context)
        if current == expected:
            opened.revision = current
            return current
        guard = self._asset_edit_guards.get((question_id, asset_id))
        if (
            guard is not None
            and guard.revision == expected
            and guard.source.is_file()
            and hashlib.sha256(guard.source.read_bytes()).hexdigest() != guard.source_hash
            and authoritative_file_snapshot(opened.context, exclude=guard.source)
            == guard.other_files
        ):
            opened.revision = current
            return current
        raise RpcError(
            CONFLICT,
            "repository changed outside the expected Ipe source edit",
            {"expectedRevision": expected, "actualRevision": current},
        )
