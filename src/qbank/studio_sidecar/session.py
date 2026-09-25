"""Shared Studio sidecar session state, helpers, and parameter parsing."""



from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from qbank.bootstrap import ProjectServices
from qbank.context import ProjectContext
from qbank.domain import RepositorySnapshot
from qbank.errors import (
    DataValidationError,
)
from qbank.models import (
    QUESTION_PATCHABLE_FIELDS,
    AssetFormat,
    AssetPackage,
    AssetPackageRepresentation,
    AssetStatus,
    QueryFilters,
    Question,
    QuestionPatch,
    SearchHit,
)
from qbank.studio_sidecar.errors import (
    INVALID_PARAMS,
    RpcError,
)
from qbank.utils import is_reparse_point

LOGGER = logging.getLogger("qbank-studio-sidecar")

MEDIA_FORMATS = {
    "image/png": AssetFormat.PNG,
    "image/jpeg": AssetFormat.JPEG,
    "image/svg+xml": AssetFormat.SVG,
    "image/webp": AssetFormat.WEBP,
    "application/pdf": AssetFormat.PDF,
    "application/x-ipe": AssetFormat.IPE,
}

@dataclass(slots=True)
class OpenRepository:
    context: ProjectContext
    services: ProjectServices
    snapshot: RepositorySnapshot
    revision: str
    projection_revision: str

@dataclass(frozen=True, slots=True)
class SnapshotQuestionRepository:
    """Expose one session snapshot through qbank's read-only repository port."""

    snapshot: RepositorySnapshot

    def scan(self) -> RepositorySnapshot:
        return self.snapshot

@dataclass(frozen=True, slots=True)
class AssetEditGuard:
    """Session-local proof that only one externally edited source changed."""

    revision: str
    source: Path
    source_hash: str
    other_files: tuple[tuple[str, str], ...]

class StudioSession:
    """Shared state and core session operations for Studio Protocol mixins."""

    repository: OpenRepository | None
    shutdown_requested: bool
    _asset_edit_guards: dict[tuple[str, str], AssetEditGuard]


    def _opened(self) -> OpenRepository:
        raise NotImplementedError



    @staticmethod
    def _ensure_projection_current(opened: OpenRepository) -> None:
        raise NotImplementedError



    @staticmethod
    def _refresh_revision(opened: OpenRepository) -> str:
        raise NotImplementedError



    @classmethod
    def _refresh_snapshot(cls, opened: OpenRepository) -> str:
        raise NotImplementedError



    @classmethod
    def _synchronize_snapshot(cls, opened: OpenRepository) -> None:
        raise NotImplementedError



    @staticmethod
    def _require_current_revision(params: dict[str, Any], opened: OpenRepository) -> str:
        raise NotImplementedError



    def _validate_source(self, question_id: str, source: str) -> dict[str, Any]:
        raise NotImplementedError



def summary_hit(hit: SearchHit) -> dict[str, Any]:
    """Normalize an index projection to the stable Studio question summary."""

    return {
        "id": hit.id,
        "title": hit.title,
        "subject": hit.subject or "",
        "chapter": hit.chapter or None,
        "topics": hit.topics.split(),
        "type": hit.question_type or "other",
        "status": hit.status or "draft",
        "difficulty": hit.difficulty or 1,
        "language": hit.language or "",
        "createdAt": hit.created_at,
    }

def question_patch(previous: Question, candidate: Question) -> QuestionPatch:
    values = candidate.model_dump(mode="json")
    set_values = {
        field: values[field]
        for field in QUESTION_PATCHABLE_FIELDS
        if getattr(previous, field) != getattr(candidate, field)
    }
    previous_topics = set(previous.topics)
    candidate_topics = set(candidate.topics)
    return QuestionPatch(
        set=set_values,
        add_topics=[item for item in candidate.topics if item not in previous_topics],
        remove_topics=[item for item in previous.topics if item not in candidate_topics],
    )

def asset_package(params: dict[str, Any], question_id: str, asset_id: str) -> AssetPackage:
    representation = asset_representation(params, "original")
    return AssetPackage(
        schema_version="1.0",
        question_id=question_id,
        asset_id=asset_id,
        role=optional_string(params, "role", default="figure"),
        status=AssetStatus.RAW,
        suggested_render=(
            None if representation.format == AssetFormat.IPE else representation.representation_id
        ),
        representations=[representation],
        provenance={"type": "studio-user-import"},
    )

def asset_representation(params: dict[str, Any], purpose: str) -> AssetPackageRepresentation:
    media_type = required_string(params, "mediaType")
    format_ = MEDIA_FORMATS.get(media_type)
    if format_ is None:
        raise RpcError(INVALID_PARAMS, f"unsupported asset media type: {media_type}")
    encoded = required_string(params, "dataBase64")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, "dataBase64 is not valid Base64") from exc
    if len(raw) > 32 * 1024 * 1024:
        raise RpcError(INVALID_PARAMS, "asset input exceeds the 32 MiB Studio limit")
    digest = hashlib.sha256(raw).hexdigest()
    identifier = f"{purpose}-{digest[:8]}"
    return AssetPackageRepresentation(
        representation_id=identifier,
        format=format_,
        base64=encoded,
        purpose=purpose,
        editable=format_ == AssetFormat.IPE,
        content_hash=digest,
    )

def required_string(params: dict[str, Any], name: str, *, allow_empty: bool = False) -> str:
    value = params.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise RpcError(INVALID_PARAMS, f"{name} must be a string")
    return value

def optional_string(params: dict[str, Any], name: str, *, default: str) -> str:
    value = params.get(name, default)
    if not isinstance(value, str):
        raise RpcError(INVALID_PARAMS, f"{name} must be a string")
    return value

def optional_int(params: dict[str, Any], name: str, default: int) -> int:
    value = params.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RpcError(INVALID_PARAMS, f"{name} must be an integer")
    return value

def string_list(params: dict[str, Any], name: str, *, allow_empty: bool = True) -> list[str]:
    value: object = params.get(name)
    if not isinstance(value, list):
        suffix = "" if allow_empty else " and must not be empty"
        raise RpcError(INVALID_PARAMS, f"{name} must be an array of strings{suffix}")
    raw_items = cast(list[object], value)
    if not all(isinstance(item, str) and item.strip() for item in raw_items) or (
        not allow_empty and not raw_items
    ):
        suffix = "" if allow_empty else " and must not be empty"
        raise RpcError(INVALID_PARAMS, f"{name} must be an array of strings{suffix}")
    items = cast(list[str], raw_items)
    return list(dict.fromkeys(item.strip() for item in items))

def optional_string_list(params: dict[str, Any], name: str) -> list[str]:
    value = params.get(name, [])
    if value == []:
        return []
    return string_list(params, name)

def object_value(params: dict[str, Any], name: str) -> dict[str, Any]:
    value: object = params.get(name)
    if not isinstance(value, dict):
        raise RpcError(INVALID_PARAMS, f"{name} must be an object")
    return cast(dict[str, Any], value)

def query_filters(params: dict[str, Any]) -> QueryFilters:
    values: dict[str, Any] = {
        "offset": optional_int(params, "offset", 0),
        "limit": optional_int(params, "limit", 500),
    }
    aliases = {
        "subject": "subject",
        "chapter": "chapter",
        "topics": "topics",
        "excludedTopics": "excluded_topics",
        "topicMode": "topic_mode",
        "type": "question_type",
        "status": "status",
        "difficultyMin": "difficulty_min",
        "difficultyMax": "difficulty_max",
        "language": "language",
        "year": "year",
        "text": "text",
    }
    for source, target in aliases.items():
        if source in params and params[source] is not None:
            values[target] = params[source]
    return QueryFilters.model_validate(values)

def authoritative_file_snapshot(
    context: ProjectContext,
    *,
    exclude: Path,
) -> tuple[tuple[str, str], ...]:
    root = context.root.resolve(strict=True)
    excluded = exclude.resolve(strict=True)
    candidates = [
        context.root / "qbank.yaml",
        context.root / "taxonomy.yaml",
        context.root / "views.yaml",
    ]
    for directory in (
        context.paths.questions,
        context.paths.assets,
        context.paths.papers,
    ):
        if directory.exists():
            candidates.extend(item for item in directory.rglob("*") if item.is_file())
    snapshot: list[tuple[str, str]] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise DataValidationError(
                f"authoritative path escapes the repository: {candidate}"
            ) from exc
        if is_reparse_point(candidate):
            raise DataValidationError(
                f"reparse points are not supported in authoritative data: {candidate}"
            )
        if resolved == excluded:
            continue
        snapshot.append((relative, hashlib.sha256(resolved.read_bytes()).hexdigest()))
    return tuple(sorted(set(snapshot)))
