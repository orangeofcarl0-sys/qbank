"""Manifest-level asset operations: lookup, package merge, and lifecycle."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from qbank.domain import NormalizedAssetInput
from qbank.errors import AssetConflictError, AssetNotFoundError, DataValidationError
from qbank.models import (
    AssetFormat,
    AssetManifest,
    AssetPackage,
    AssetRepresentation,
    AssetStatus,
    Diagnostic,
    DiagnosticCode,
)


def updated_manifest(manifest: AssetManifest, **changes: object) -> AssetManifest:
    values = manifest.model_dump(mode="python")
    values.update(changes)
    return AssetManifest.model_validate(values)


def optional_representation(
    manifest: AssetManifest,
    representation_id: str | None,
) -> AssetRepresentation | None:
    if representation_id is None:
        return None
    return next(
        (item for item in manifest.representations if item.representation_id == representation_id),
        None,
    )


def find_representation(
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


def editor_representation(manifest: AssetManifest) -> AssetRepresentation:
    if manifest.preferred_editor is not None:
        return find_representation(manifest, manifest.preferred_editor)
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


def ipe_source(manifest: AssetManifest) -> AssetRepresentation:
    editor = editor_representation(manifest)
    if editor.format == AssetFormat.IPE:
        return editor
    for candidate in manifest.representations:
        if candidate.format == AssetFormat.IPE and candidate.editable:
            return candidate
    raise DataValidationError(
        f"asset_command_rejected: asset has no editable Ipe source: {manifest.asset_id}"
    )


def merge_package(
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
        return manifest, content_files(normalized), "create"
    additions = _new_package_representations(existing, normalized)
    manifest = updated_manifest(
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
    return manifest, content_files(additions), action


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


def content_files(
    normalized: Sequence[NormalizedAssetInput],
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for item in normalized:
        path = item.representation.path
        content = item.content
        if path is not None and content is not None:
            files[path] = content
    return files


def versioned_replacement(
    normalized: NormalizedAssetInput,
    manifest: AssetManifest,
) -> NormalizedAssetInput:
    representation_item = normalized.representation
    if representation_item.content_hash is None:
        return normalized
    base = representation_item.representation_id
    identifier = f"{base}-{representation_item.content_hash[:8]}"
    if any(item.representation_id == identifier for item in manifest.representations):
        raise AssetConflictError(f"asset_conflict: replacement already exists: {identifier}")
    suffix = PureSuffix.from_path(representation_item.path)
    updated = AssetRepresentation.model_validate(
        {
            **representation_item.model_dump(mode="python"),
            "representation_id": identifier,
            "path": f"{identifier}{suffix}",
            "derived_from": representation_item.derived_from or manifest.preferred_render,
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


def lifecycle_warnings(manifest: AssetManifest) -> list[Diagnostic]:
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
