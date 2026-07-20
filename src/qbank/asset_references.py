"""Pure parsing of legacy and logical Markdown image references.

This module deliberately has no dependency on the asset application service or
filesystem adapters.  It lets validation, rendering, and compatibility code
share one URI grammar without an import cycle through the composition root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

from qbank.models import ASSET_ID_PATTERN, Question
from qbank.question_layout import QUESTION_CONTENT_FIELDS


class AssetKind(StrEnum):
    """Supported image-resource classifications."""

    LOCAL = "local"
    LOGICAL = "logical"
    EXTERNAL = "external"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class AssetReference:
    """A classified image URI and optional normalized local path."""

    raw: str
    kind: AssetKind
    normalized: str | None = None
    asset_id: str | None = None
    representation_id: str | None = None


def classify_resource_uri(uri: str) -> AssetReference:
    """Classify and normalize one Markdown or YAML resource reference."""
    value = uri.strip()
    parsed = urlsplit(value)
    if parsed.scheme == "asset":
        asset_id = parsed.path
        representation_id = parsed.fragment or None
        valid = (
            not parsed.netloc
            and not parsed.query
            and re.fullmatch(ASSET_ID_PATTERN, asset_id) is not None
            and (
                representation_id is None
                or re.fullmatch(ASSET_ID_PATTERN, representation_id) is not None
            )
        )
        if valid:
            return AssetReference(
                raw=uri,
                kind=AssetKind.LOGICAL,
                normalized=(
                    f"asset:{asset_id}#{representation_id}"
                    if representation_id is not None
                    else f"asset:{asset_id}"
                ),
                asset_id=asset_id,
                representation_id=representation_id,
            )
        return AssetReference(raw=uri, kind=AssetKind.INVALID)
    if parsed.scheme in {"http", "https"} or (not parsed.scheme and parsed.netloc):
        return AssetReference(raw=uri, kind=AssetKind.EXTERNAL)
    decoded = unquote(parsed.path).replace("\\", "/")
    path = PurePosixPath(decoded)
    invalid = (
        not value
        or bool(parsed.scheme)
        or bool(parsed.netloc)
        or bool(parsed.query)
        or Path(decoded).is_absolute()
        or path.is_absolute()
        or bool(path.parts and ":" in path.parts[0])
        or ".." in path.parts
    )
    normalized = path.as_posix()
    if invalid or normalized in {"", "."}:
        return AssetReference(raw=uri, kind=AssetKind.INVALID)
    return AssetReference(raw=uri, kind=AssetKind.LOCAL, normalized=normalized)


def extract_image_resources(question: Question) -> dict[str, set[str]]:
    """Extract image destinations from Markdown tokens for every body field."""
    parser = MarkdownIt("commonmark", {"html": False})
    parser.validateLink = _allow_link
    resources: dict[str, set[str]] = {}
    for field in QUESTION_CONTENT_FIELDS:
        for source in _image_sources(parser.parse(getattr(question, field))):
            resources.setdefault(source, set()).add(field)
    return resources


def extract_markdown_image_resources(markdown: str) -> set[str]:
    """Extract image destinations from one already-rendered Markdown document."""
    parser = MarkdownIt("commonmark", {"html": False})
    parser.validateLink = _allow_link
    return set(_image_sources(parser.parse(markdown)))


def _image_sources(tokens: list[Token]) -> list[str]:
    sources: list[str] = []
    for token in tokens:
        if token.type == "image":
            source = token.attrGet("src")
            if isinstance(source, str) and source:
                sources.append(source)
        if token.children:
            sources.extend(_image_sources(token.children))
    return sources


def _allow_link(url: str) -> bool:
    del url
    return True
