"""Asset edit sessions: working copies, reconciliation, and restore."""

from __future__ import annotations

import hashlib
from pathlib import Path

from qbank.application.asset_manifest import optional_representation, updated_manifest
from qbank.errors import DataValidationError
from qbank.models import AssetCommandResult, AssetManifest, AssetRepresentation, AssetStatus


def edit_working_copy(
    manifest: AssetManifest,
    editor: AssetRepresentation,
    content: bytes,
) -> tuple[AssetManifest, AssetRepresentation]:
    identifier = _next_edit_identifier(manifest, editor.representation_id)
    suffix = Path(editor.path or "").suffix.lower()
    working = AssetRepresentation.model_validate(
        {
            **editor.model_dump(mode="python"),
            "representation_id": identifier,
            "path": f"{identifier}{suffix}",
            "derived_from": editor.representation_id,
            "content_hash": hashlib.sha256(content).hexdigest(),
            "metadata": {
                **editor.metadata,
                "working_copy": True,
                "edit_base_hash": editor.content_hash,
            },
        }
    )
    return (
        updated_manifest(
            manifest,
            preferred_editor=identifier,
            representations=[*manifest.representations, working],
            status=AssetStatus.EDITING,
        ),
        working,
    )


def _next_edit_identifier(manifest: AssetManifest, base: str) -> str:
    occupied = {item.representation_id for item in manifest.representations}
    index = 1
    while f"{base}-edit-{index}" in occupied:
        index += 1
    return f"{base}-edit-{index}"


def edit_command_result(
    manifest: AssetManifest,
    editor: AssetRepresentation,
    target: Path,
    command: tuple[str, ...],
    *,
    dry_run: bool,
) -> AssetCommandResult:
    return AssetCommandResult(
        ok=True,
        dry_run=dry_run,
        action="edit",
        question_id=manifest.question_id,
        asset_id=manifest.asset_id,
        representation_id=editor.representation_id,
        target=str(target),
        command=list(command),
    )


def reconciled_editor_manifest(
    manifest: AssetManifest,
    editor: AssetRepresentation,
    digest: str,
) -> AssetManifest:
    representations: list[AssetRepresentation] = []
    for item in manifest.representations:
        if item.representation_id == editor.representation_id:
            metadata = {
                **item.metadata,
                "previous_content_hash": item.content_hash,
            }
            representations.append(
                item.model_copy(update={"content_hash": digest, "metadata": metadata})
            )
        elif item.renderable and item.purpose == "render":
            representations.append(item.model_copy(update={"stale": True}))
        else:
            representations.append(item)
    return updated_manifest(
        manifest,
        representations=representations,
        status=AssetStatus.EDITING,
    )


def restored_manifest(
    manifest: AssetManifest,
) -> tuple[AssetManifest, dict[str, object]]:
    editor = optional_representation(manifest, manifest.preferred_editor)
    render = optional_representation(manifest, manifest.preferred_render)
    previous_editor = _editable_parent(manifest, editor)
    previous_render = _render_parent(manifest, render, previous_editor)
    if previous_editor is None and previous_render is None:
        raise DataValidationError(
            f"asset_command_rejected: no previous version for asset: {manifest.asset_id}"
        )
    changes: dict[str, object] = {}
    values: dict[str, object] = {"status": AssetStatus.EDITING}
    if previous_editor is not None:
        values["preferred_editor"] = previous_editor.representation_id
        changes["preferred_editor"] = previous_editor.representation_id
    if previous_render is not None:
        values["preferred_render"] = previous_render.representation_id
        values["representations"] = [
            item.model_copy(update={"stale": False})
            if item.representation_id == previous_render.representation_id
            else item
            for item in manifest.representations
        ]
        changes["preferred_render"] = previous_render.representation_id
    return updated_manifest(manifest, **values), changes


def _editable_parent(
    manifest: AssetManifest,
    current: AssetRepresentation | None,
) -> AssetRepresentation | None:
    if current is None or current.derived_from is None:
        return None
    parent = optional_representation(manifest, current.derived_from)
    return parent if parent is not None and parent.editable else None


def _render_parent(
    manifest: AssetManifest,
    current: AssetRepresentation | None,
    previous_editor: AssetRepresentation | None,
) -> AssetRepresentation | None:
    if current is not None:
        supersedes = current.metadata.get("supersedes")
        if isinstance(supersedes, str):
            candidate = optional_representation(manifest, supersedes)
            if candidate is not None and candidate.renderable:
                return candidate
        if current.derived_from is not None:
            candidate = optional_representation(manifest, current.derived_from)
            if candidate is not None and candidate.renderable:
                return candidate
    if previous_editor is None:
        return None
    candidates = [
        item
        for item in manifest.representations
        if item.renderable and item.derived_from == previous_editor.representation_id
    ]
    return candidates[-1] if candidates else None
