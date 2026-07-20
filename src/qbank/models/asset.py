"""Logical question-asset and package exchange models."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from qbank.models.common import SchemaVersion, StrictModel
from qbank.models.question import ID_PATTERN

ASSET_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
CONTENT_HASH_PATTERN = r"^[0-9a-f]{64}$"
RENDER_FORMATS = frozenset({"png", "jpeg", "pdf", "svg", "webp", "gif", "bmp"})


class AssetStatus(StrEnum):
    """Lifecycle states for one logical asset."""

    RAW = "raw"
    NEEDS_REDRAW = "needs_redraw"
    EDITING = "editing"
    REVIEWED = "reviewed"
    FINAL = "final"
    FAILED = "failed"


class AssetFormat(StrEnum):
    """Representations understood by the built-in adapters."""

    PNG = "png"
    JPEG = "jpeg"
    PDF = "pdf"
    SVG = "svg"
    TIKZ = "tikz"
    IPE = "ipe"
    WEBP = "webp"
    GIF = "gif"
    BMP = "bmp"
    URL = "url"
    OTHER = "other"


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized == "."
        or Path(value).is_absolute()
        or path.is_absolute()
        or ":" in path.parts[0]
        or ".." in path.parts
    ):
        raise ValueError("representation path must be relative without '..'")
    return path.as_posix()


def _http_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("representation URL must use HTTP or HTTPS")
    return value.strip()


class AssetRepresentation(StrictModel):
    """One durable source, editable form, or rendered derivative."""

    representation_id: str = Field(pattern=ASSET_ID_PATTERN)
    format: AssetFormat
    path: str | None = None
    url: str | None = None
    purpose: str = Field(min_length=1)
    editable: bool = False
    derived_from: str | None = Field(default=None, pattern=ASSET_ID_PATTERN)
    stale: bool = False
    content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_is_well_formed(self) -> AssetRepresentation:
        """Require exactly one durable location and a hash for local content."""
        if (self.path is None) == (self.url is None):
            raise ValueError("representation must define exactly one of path or url")
        if self.path is not None:
            self.path = _safe_relative_path(self.path)
            if self.content_hash is None:
                raise ValueError("local representation requires content_hash")
        if self.url is not None:
            self.url = _http_url(self.url)
        return self

    @property
    def renderable(self) -> bool:
        """Return whether the representation can be embedded as an image."""
        return self.url is not None or self.format.value in RENDER_FORMATS


class AssetManifest(StrictModel):
    """Authoritative ``asset.yaml`` for one logical question asset."""

    schema_version: SchemaVersion
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    question_id: str = Field(pattern=ID_PATTERN)
    role: str = Field(min_length=1)
    status: AssetStatus
    preferred_editor: str | None = Field(default=None, pattern=ASSET_ID_PATTERN)
    preferred_render: str | None = Field(default=None, pattern=ASSET_ID_PATTERN)
    representations: list[AssetRepresentation] = Field(min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)
    review_notes: str = ""

    @model_validator(mode="after")
    def references_are_consistent(self) -> AssetManifest:
        """Validate representation identity, preferences, and derivation links."""
        by_id = {item.representation_id: item for item in self.representations}
        if len(by_id) != len(self.representations):
            raise ValueError("representation_id values must be unique")
        if self.preferred_editor is not None:
            editor = by_id.get(self.preferred_editor)
            if editor is None or not editor.editable:
                raise ValueError("preferred_editor must name an editable representation")
        if self.preferred_render is not None:
            render = by_id.get(self.preferred_render)
            if render is None or not render.renderable:
                raise ValueError("preferred_render must name a renderable representation")
        for representation in self.representations:
            parent = representation.derived_from
            if parent is not None and parent not in by_id:
                raise ValueError(f"derived_from references an unknown representation: {parent}")
            if parent == representation.representation_id:
                raise ValueError("representation cannot derive from itself")
        _reject_derivation_cycles(by_id)
        return self


def _reject_derivation_cycles(by_id: dict[str, AssetRepresentation]) -> None:
    for representation_id in by_id:
        seen: set[str] = set()
        current: str | None = representation_id
        while current is not None:
            if current in seen:
                raise ValueError("representation derivation graph contains a cycle")
            seen.add(current)
            current = by_id[current].derived_from


class AssetPackageRepresentation(StrictModel):
    """One untrusted representation supplied by an input package."""

    representation_id: str = Field(pattern=ASSET_ID_PATTERN)
    format: AssetFormat
    path: str | None = None
    url: str | None = None
    data_uri: str | None = None
    base64: str | None = None
    inline_tikz: str | None = None
    purpose: str = Field(min_length=1)
    editable: bool = False
    derived_from: str | None = Field(default=None, pattern=ASSET_ID_PATTERN)
    content_hash: str | None = Field(default=None, pattern=CONTENT_HASH_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_input_source(self) -> AssetPackageRepresentation:
        """Require exactly one supported package input representation."""
        values = (self.path, self.url, self.data_uri, self.base64, self.inline_tikz)
        if sum(value is not None for value in values) != 1:
            raise ValueError(
                "package representation must define exactly one of "
                "path, url, data_uri, base64, or inline_tikz"
            )
        if self.path is not None:
            self.path = _safe_relative_path(self.path)
        if self.url is not None:
            self.url = _http_url(self.url)
        if self.inline_tikz is not None and not self.inline_tikz.strip():
            raise ValueError("inline_tikz must not be empty")
        if self.data_uri is not None and not self.data_uri.startswith("data:"):
            raise ValueError("data_uri must start with 'data:'")
        if self.base64 is not None and not re.fullmatch(r"[A-Za-z0-9+/=\s]+", self.base64):
            raise ValueError("base64 contains invalid characters")
        return self


class AssetPackage(StrictModel):
    """Stable exchange contract produced by digitization projects."""

    schema_version: SchemaVersion
    question_id: str = Field(pattern=ID_PATTERN)
    asset_id: str = Field(pattern=ASSET_ID_PATTERN)
    role: str = Field(min_length=1)
    representations: list[AssetPackageRepresentation] = Field(min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)
    suggested_editor: str | None = Field(default=None, pattern=ASSET_ID_PATTERN)
    suggested_render: str | None = Field(default=None, pattern=ASSET_ID_PATTERN)
    status: AssetStatus = AssetStatus.RAW
    review_notes: str = ""

    @model_validator(mode="after")
    def suggestions_are_valid(self) -> AssetPackage:
        """Keep package identity and suggested preferences internally consistent."""
        by_id = {item.representation_id: item for item in self.representations}
        if len(by_id) != len(self.representations):
            raise ValueError("representation_id values must be unique")
        if self.suggested_editor is not None:
            editor = by_id.get(self.suggested_editor)
            if editor is None or not editor.editable:
                raise ValueError("suggested_editor must name an editable representation")
        if self.suggested_render is not None:
            render = by_id.get(self.suggested_render)
            if render is None:
                raise ValueError("suggested_render must name a representation")
        for representation in self.representations:
            parent = representation.derived_from
            if parent is not None and parent not in by_id:
                raise ValueError(f"derived_from references an unknown representation: {parent}")
        return self
