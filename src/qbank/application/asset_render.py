"""Rendered-asset representation merging and preference resolution."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from qbank.application.asset_manifest import optional_representation, updated_manifest
from qbank.domain import RenderedAsset
from qbank.models import AssetFormat, AssetManifest, AssetRepresentation, AssetStatus


def merge_rendered(
    manifest: AssetManifest,
    source: AssetRepresentation,
    rendered: Sequence[RenderedAsset],
) -> tuple[AssetManifest, dict[str, bytes], list[str]]:
    representations = list(manifest.representations)
    files: dict[str, bytes] = {}
    generated: list[str] = []
    known_hashes = _known_representation_hashes(representations)
    previous = optional_representation(manifest, manifest.preferred_render)
    for value in rendered:
        content = value.content
        format_ = value.format
        digest = hashlib.sha256(content).hexdigest()
        existing_id = known_hashes.get(digest)
        if existing_id is not None:
            representations = [
                item.model_copy(update={"stale": False})
                if item.representation_id == existing_id
                else item
                for item in representations
            ]
            generated.append(existing_id)
            continue
        identifier = f"render-{format_.value}-{digest[:8]}"
        filename = f"{identifier}.{_extension(format_)}"
        metadata = dict(value.metadata)
        if previous is not None and previous.format == format_:
            metadata["supersedes"] = previous.representation_id
        representation = AssetRepresentation(
            representation_id=identifier,
            format=format_,
            path=filename,
            purpose="render",
            editable=False,
            derived_from=source.representation_id,
            stale=False,
            content_hash=digest,
            metadata=metadata,
        )
        representations.append(representation)
        files[filename] = content
        generated.append(identifier)
        known_hashes[digest] = identifier
    preferred = _render_preference(manifest, representations, generated)
    updated = updated_manifest(
        manifest,
        representations=representations,
        preferred_render=preferred,
        status=AssetStatus.EDITING,
    )
    return updated, files, generated


def _known_representation_hashes(
    representations: Sequence[AssetRepresentation],
) -> dict[str, str]:
    return {
        item.content_hash: item.representation_id
        for item in representations
        if item.content_hash is not None
    }


def _render_preference(
    manifest: AssetManifest,
    representations: Sequence[AssetRepresentation],
    generated: list[str],
) -> str | None:
    previous = optional_representation(manifest, manifest.preferred_render)
    if previous is not None and not previous.stale:
        return previous.representation_id
    by_id = {item.representation_id: item for item in representations}
    if previous is not None:
        same_format = [
            identifier for identifier in generated if by_id[identifier].format == previous.format
        ]
        if same_format:
            return same_format[0]
    return generated[0] if generated else manifest.preferred_render


def _extension(format_: AssetFormat) -> str:
    return "jpg" if format_ == AssetFormat.JPEG else format_.value
