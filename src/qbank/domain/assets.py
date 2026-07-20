"""Pure logical-asset selection and mutation plan contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from qbank.models import AssetFormat, AssetManifest, AssetRepresentation

AssetTarget = Literal["generic", "preview", "html", "md", "docx", "pdf"]

TARGET_FORMAT_PREFERENCES: dict[AssetTarget, tuple[AssetFormat, ...]] = {
    "generic": (
        AssetFormat.SVG,
        AssetFormat.PNG,
        AssetFormat.JPEG,
        AssetFormat.PDF,
        AssetFormat.WEBP,
        AssetFormat.GIF,
        AssetFormat.BMP,
        AssetFormat.URL,
    ),
    "preview": (
        AssetFormat.SVG,
        AssetFormat.PNG,
        AssetFormat.JPEG,
        AssetFormat.WEBP,
        AssetFormat.GIF,
        AssetFormat.PDF,
        AssetFormat.URL,
    ),
    "html": (
        AssetFormat.SVG,
        AssetFormat.PNG,
        AssetFormat.JPEG,
        AssetFormat.WEBP,
        AssetFormat.GIF,
        AssetFormat.URL,
    ),
    "md": (
        AssetFormat.SVG,
        AssetFormat.PNG,
        AssetFormat.JPEG,
        AssetFormat.WEBP,
        AssetFormat.GIF,
        AssetFormat.PDF,
        AssetFormat.URL,
    ),
    "docx": (
        AssetFormat.PNG,
        AssetFormat.JPEG,
        AssetFormat.BMP,
        AssetFormat.SVG,
        AssetFormat.PDF,
    ),
    "pdf": (
        AssetFormat.PDF,
        AssetFormat.SVG,
        AssetFormat.PNG,
        AssetFormat.JPEG,
    ),
}


@dataclass(frozen=True, slots=True)
class NormalizedAssetInput:
    """One package source normalized without writing authoritative storage."""

    representation: AssetRepresentation
    content: bytes | None


@dataclass(frozen=True, slots=True)
class RenderedAsset:
    """One successful adapter output staged in memory."""

    format: AssetFormat
    content: bytes
    command: tuple[str, ...]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AssetHistoryEvent:
    """One append-only asset operation record."""

    operation: str
    question_id: str
    asset_id: str
    representation_ids: tuple[str, ...]
    changes: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class AssetLocation:
    """Containment-safe paths owned by one registered logical asset."""

    directory: Path
    manifest: Path
    relative_manifest: str


def select_asset_representation(
    manifest: AssetManifest,
    target: AssetTarget,
    *,
    requested: str | None = None,
) -> AssetRepresentation | None:
    """Select an explicit/preferred compatible representation, then fall back."""
    preferences = TARGET_FORMAT_PREFERENCES[target]
    by_id = {item.representation_id: item for item in manifest.representations}
    if requested is not None:
        candidate = by_id.get(requested)
        return candidate if candidate is not None and candidate.format in preferences else None
    if manifest.preferred_render is not None:
        candidate = by_id[manifest.preferred_render]
        if candidate.format in preferences:
            return candidate
    rank = {format_: index for index, format_ in enumerate(preferences)}
    compatible = [
        item for item in manifest.representations if item.renderable and item.format in rank
    ]
    if not compatible:
        return None
    return min(
        compatible,
        key=lambda item: (rank[item.format], item.representation_id),
    )


def asset_legacy_references(provenance: dict[str, Any]) -> set[str]:
    """Return compatibility references explicitly preserved by a package."""
    values: set[str] = set()
    for key in ("legacy_reference", "original_asset_path"):
        value = provenance.get(key)
        if isinstance(value, str):
            values.add(value)
    multiple = provenance.get("legacy_references")
    if isinstance(multiple, list):
        values.update(item for item in cast(list[object], multiple) if isinstance(item, str))
    return values
