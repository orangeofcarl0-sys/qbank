"""Filesystem storage and input normalization for logical assets."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import shutil
import time
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote_to_bytes, urlsplit

from pydantic import ValidationError
from ruamel.yaml.error import YAMLError

from qbank.context import ProjectContext
from qbank.domain import (
    AssetHistoryEvent,
    AssetLocation,
    NormalizedAssetInput,
    asset_legacy_references,
)
from qbank.errors import (
    AssetConflictError,
    AssetNotFoundError,
    DataValidationError,
)
from qbank.models import (
    ASSET_ID_PATTERN,
    AssetFormat,
    AssetHistoryEntry,
    AssetManifest,
    AssetPackageRepresentation,
    AssetRepresentation,
    Diagnostic,
    DiagnosticCode,
)
from qbank.transaction import MutationTransaction
from qbank.utils import is_relative_to, reject_reparse_points, utc_now
from qbank.yaml_io import dump_yaml, load_yaml

_DATA_URI = re.compile(r"^data:([^;,]*)(;base64)?,(.*)$", re.DOTALL)
_FORMAT_EXTENSIONS: dict[AssetFormat, str] = {
    AssetFormat.PNG: ".png",
    AssetFormat.JPEG: ".jpg",
    AssetFormat.PDF: ".pdf",
    AssetFormat.SVG: ".svg",
    AssetFormat.TIKZ: ".tex",
    AssetFormat.IPE: ".ipe",
    AssetFormat.WEBP: ".webp",
    AssetFormat.GIF: ".gif",
    AssetFormat.BMP: ".bmp",
    AssetFormat.OTHER: ".bin",
    AssetFormat.URL: ".bin",
}
_MIME_FORMATS = {
    "image/png": AssetFormat.PNG,
    "image/jpeg": AssetFormat.JPEG,
    "application/pdf": AssetFormat.PDF,
    "image/svg+xml": AssetFormat.SVG,
    "image/webp": AssetFormat.WEBP,
    "image/gif": AssetFormat.GIF,
    "image/bmp": AssetFormat.BMP,
}


class FileAssetRepository:
    """Store one authoritative manifest below each question/asset directory."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def list(
        self,
        question_id: str | None = None,
        *,
        strict: bool = True,
    ) -> tuple[AssetManifest, ...]:
        manifests, diagnostics = self._scan(question_id)
        if strict and diagnostics:
            payload = [item.model_dump(mode="json", exclude_none=True) for item in diagnostics]
            raise DataValidationError(
                "asset_manifest_invalid: " + json.dumps(payload, ensure_ascii=False)
            )
        return manifests

    def get(self, question_id: str, asset_id: str) -> AssetManifest:
        location = self.location(question_id, asset_id)
        if not location.manifest.is_file():
            raise AssetNotFoundError(
                f"asset_not_found: asset does not exist: {question_id}/{asset_id}"
            )
        try:
            return self._read_manifest(location.manifest)
        except (OSError, UnicodeError, YAMLError, ValidationError, ValueError) as exc:
            raise DataValidationError(
                f"asset_manifest_invalid: {location.relative_manifest}: {exc}"
            ) from exc

    def find_by_reference(
        self,
        question_id: str,
        reference: str,
    ) -> AssetManifest | None:
        for manifest in self.list(question_id, strict=False):
            values = asset_legacy_references(manifest.provenance)
            if reference in values:
                return manifest
        return None

    def location(self, question_id: str, asset_id: str) -> AssetLocation:
        _validate_identifier(question_id, "question_id")
        _validate_identifier(asset_id, "asset_id")
        assets_root = self.context.paths.assets.resolve()
        lexical = assets_root / question_id / asset_id
        try:
            reject_reparse_points(lexical, boundary=assets_root)
        except ValueError as exc:
            raise DataValidationError(
                "asset_path_escape: asset path contains a reparse point"
            ) from exc
        directory = lexical.resolve()
        if not is_relative_to(directory, assets_root):
            raise DataValidationError("asset_path_escape: asset directory escapes assets root")
        manifest = directory / "asset.yaml"
        return AssetLocation(
            directory=directory,
            manifest=manifest,
            relative_manifest=manifest.relative_to(self.context.root).as_posix(),
        )

    def representation_path(
        self,
        manifest: AssetManifest,
        representation_id: str,
    ) -> Path | None:
        representation = _representation(manifest, representation_id)
        if representation.path is None:
            return None
        location = self.location(manifest.question_id, manifest.asset_id)
        lexical = location.directory / representation.path
        try:
            reject_reparse_points(lexical, boundary=location.directory)
        except ValueError as exc:
            raise DataValidationError(
                "asset_path_escape: representation contains a reparse point"
            ) from exc
        candidate = lexical.resolve()
        if not is_relative_to(candidate, location.directory):
            raise DataValidationError(
                "asset_path_escape: representation path escapes its asset directory"
            )
        return candidate

    def commit(
        self,
        manifest: AssetManifest,
        files: Mapping[str, bytes],
        event: AssetHistoryEvent,
    ) -> None:
        location = self.location(manifest.question_id, manifest.asset_id)
        expected = {item.path for item in manifest.representations if item.path is not None}
        transaction = MutationTransaction.for_context(self.context)
        for relative, content in sorted(files.items()):
            if relative not in expected:
                raise DataValidationError(
                    f"asset_command_rejected: unregistered representation write: {relative}"
                )
            destination = _contained_file(location.directory, relative)
            if destination.is_file() and destination.read_bytes() != content:
                raise AssetConflictError(
                    f"asset_conflict: refusing to overwrite representation: {destination}"
                )
            transaction.write_bytes(destination, content)
        manifest_text = dump_yaml(manifest.model_dump(mode="json", exclude_none=True)) + "\n"
        transaction.write(location.manifest, manifest_text)
        history_path, history_text = self._history(event)
        transaction.write(history_path, history_text)
        transaction.commit()

    def record(self, event: AssetHistoryEvent) -> None:
        path, text = self._history(event)
        transaction = MutationTransaction.for_context(self.context)
        transaction.write(path, text)
        transaction.commit()

    def discard_new(self, question_id: str, asset_id: str) -> None:
        """Remove a just-created asset and only its matching history entries."""
        location = self.location(question_id, asset_id)
        if location.directory.is_dir():
            shutil.rmtree(location.directory)
        parent = location.directory.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
        history_root = self.context.paths.state / "asset-history"
        if not history_root.is_dir():
            return
        for path in history_root.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                event = AssetHistoryEntry.model_validate(value)
            except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
                continue
            if event.question_id == question_id and event.asset_id == asset_id:
                path.unlink()

    def history(
        self,
        question_id: str,
        asset_id: str | None = None,
    ) -> tuple[AssetHistoryEntry, ...]:
        """Read append-only events for one question or one logical asset."""
        root = self.context.paths.state / "asset-history"
        if not root.is_dir():
            return ()
        events: list[AssetHistoryEntry] = []
        paths = sorted(
            root.glob("*.json"),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
        )
        for path in paths:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                event = AssetHistoryEntry.model_validate(value)
            except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
                continue
            if event.question_id != question_id:
                continue
            if asset_id is not None and event.asset_id != asset_id:
                continue
            events.append(event)
        return tuple(events)

    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self._scan()[1]

    def _scan(
        self,
        question_id: str | None = None,
    ) -> tuple[tuple[AssetManifest, ...], tuple[Diagnostic, ...]]:
        root = self.context.paths.assets
        pattern = f"{question_id}/*/asset.yaml" if question_id else "*/*/asset.yaml"
        manifests: list[AssetManifest] = []
        diagnostics: list[Diagnostic] = []
        for path in sorted(root.glob(pattern), key=lambda item: item.as_posix()):
            try:
                manifest = self._read_manifest(path)
                expected = self.location(manifest.question_id, manifest.asset_id).manifest
                if path.resolve() != expected:
                    raise ValueError("manifest directory does not match question_id/asset_id")
                manifests.append(manifest)
            except (OSError, UnicodeError, YAMLError, ValidationError, ValueError) as exc:
                diagnostics.append(
                    Diagnostic(
                        code=DiagnosticCode.ASSET_MANIFEST_INVALID,
                        file=path.relative_to(self.context.root).as_posix(),
                        message=f"invalid asset manifest: {exc}",
                    )
                )
        return tuple(manifests), tuple(diagnostics)

    @staticmethod
    def _read_manifest(path: Path) -> AssetManifest:
        raw = load_yaml(path.read_text(encoding="utf-8"))
        return AssetManifest.model_validate(raw)

    def _history(self, event: AssetHistoryEvent) -> tuple[Path, str]:
        timestamp = utc_now()
        compact = timestamp.replace(":", "").replace("-", "")
        sequence = time.time_ns()
        path = (
            self.context.paths.state
            / "asset-history"
            / (
                f"{compact}-{sequence}-{event.operation}-{event.question_id}-"
                f"{event.asset_id}-{uuid.uuid4().hex[:8]}.json"
            )
        )
        payload = {
            "timestamp": timestamp,
            "operation": event.operation,
            "question_id": event.question_id,
            "asset_id": event.asset_id,
            "representation_ids": list(event.representation_ids),
            "changes": list(event.changes),
        }
        return path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


class AssetInputAdapter:
    """Decode files, Base64/data URIs, inline TikZ, and HTTP(S) inputs."""

    def __init__(self, context: ProjectContext):
        self.max_bytes = context.config.assets.download_max_bytes

    def normalize(
        self,
        representation: AssetPackageRepresentation,
        *,
        package_root: Path,
        download: bool = False,
    ) -> NormalizedAssetInput:
        if representation.url is not None and not download:
            return _remote_input(representation)
        content, format_, suffix = self._content(
            representation,
            package_root=package_root,
        )
        digest = hashlib.sha256(content).hexdigest()
        if representation.content_hash is not None and digest != representation.content_hash:
            raise DataValidationError(
                "asset_hash_mismatch: package content does not match content_hash"
            )
        filename = f"{representation.representation_id}{suffix}"
        normalized = AssetRepresentation(
            representation_id=representation.representation_id,
            format=format_,
            path=filename,
            purpose=representation.purpose,
            editable=representation.editable,
            derived_from=representation.derived_from,
            content_hash=digest,
            metadata=representation.metadata,
        )
        return NormalizedAssetInput(representation=normalized, content=content)

    def _content(
        self,
        representation: AssetPackageRepresentation,
        *,
        package_root: Path,
    ) -> tuple[bytes, AssetFormat, str]:
        if representation.path is not None:
            return self._local_file(representation, package_root)
        if representation.data_uri is not None:
            return _decode_data_uri(representation)
        if representation.base64 is not None:
            return (
                _decode_base64(representation.base64),
                representation.format,
                _FORMAT_EXTENSIONS[representation.format],
            )
        if representation.inline_tikz is not None:
            if representation.format != AssetFormat.TIKZ:
                raise DataValidationError("asset_package_invalid: inline TikZ requires tikz format")
            return (
                representation.inline_tikz.encode("utf-8"),
                AssetFormat.TIKZ,
                ".tex",
            )
        if representation.url is not None:
            return self._download(representation)
        raise DataValidationError("asset_package_invalid: representation has no source")

    def _local_file(
        self,
        representation: AssetPackageRepresentation,
        package_root: Path,
    ) -> tuple[bytes, AssetFormat, str]:
        root = package_root.resolve()
        lexical = root / cast(str, representation.path)
        try:
            reject_reparse_points(lexical, boundary=root)
        except ValueError as exc:
            raise DataValidationError(
                "asset_path_escape: package path contains a reparse point"
            ) from exc
        source = lexical.resolve()
        if not is_relative_to(source, root):
            raise DataValidationError("asset_path_escape: package path escapes package root")
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise DataValidationError(f"asset_missing: package file is missing: {source}") from exc
        suffix = source.suffix.lower() or _FORMAT_EXTENSIONS[representation.format]
        return content, representation.format, _normalized_suffix(suffix, representation.format)

    def _download(
        self,
        representation: AssetPackageRepresentation,
    ) -> tuple[bytes, AssetFormat, str]:
        url = cast(str, representation.url)
        request = urllib.request.Request(url, headers={"User-Agent": "qbank/0.2.0"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read(self.max_bytes + 1)
                content_type = response.headers.get_content_type()
        except OSError as exc:
            raise DataValidationError(f"asset_missing: unable to download URL: {exc}") from exc
        if len(content) > self.max_bytes:
            raise DataValidationError("asset_package_invalid: downloaded asset exceeds size limit")
        format_ = _MIME_FORMATS.get(content_type, representation.format)
        suffix = _url_suffix(url) or _FORMAT_EXTENSIONS[format_]
        return content, format_, _normalized_suffix(suffix, format_)


def _remote_input(
    representation: AssetPackageRepresentation,
) -> NormalizedAssetInput:
    return NormalizedAssetInput(
        representation=AssetRepresentation(
            representation_id=representation.representation_id,
            format=representation.format,
            url=representation.url,
            purpose=representation.purpose,
            editable=representation.editable,
            derived_from=representation.derived_from,
            content_hash=representation.content_hash,
            metadata=representation.metadata,
        ),
        content=None,
    )


def _decode_data_uri(
    representation: AssetPackageRepresentation,
) -> tuple[bytes, AssetFormat, str]:
    match = _DATA_URI.fullmatch(cast(str, representation.data_uri))
    if match is None:
        raise DataValidationError("asset_package_invalid: malformed data URI")
    media_type, encoded, payload = match.groups()
    try:
        content = base64.b64decode(payload, validate=True) if encoded else unquote_to_bytes(payload)
    except (ValueError, binascii.Error) as exc:
        raise DataValidationError("asset_package_invalid: malformed data URI payload") from exc
    format_ = _MIME_FORMATS.get(media_type, representation.format)
    return content, format_, _FORMAT_EXTENSIONS[format_]


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DataValidationError("asset_package_invalid: malformed Base64 payload") from exc


def _validate_identifier(value: str, label: str) -> None:
    if re.fullmatch(ASSET_ID_PATTERN, value) is None:
        raise DataValidationError(f"asset_command_rejected: invalid {label}: {value}")


def _representation(
    manifest: AssetManifest,
    representation_id: str,
) -> AssetRepresentation:
    for representation in manifest.representations:
        if representation.representation_id == representation_id:
            return representation
    raise AssetNotFoundError(f"asset_not_found: representation does not exist: {representation_id}")


def _contained_file(directory: Path, relative: str) -> Path:
    normalized = PurePosixPath(relative.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise DataValidationError("asset_path_escape: invalid representation path")
    lexical = directory / Path(*normalized.parts)
    try:
        reject_reparse_points(lexical, boundary=directory)
    except ValueError as exc:
        raise DataValidationError(
            "asset_path_escape: representation contains a reparse point"
        ) from exc
    candidate = lexical.resolve()
    if not is_relative_to(candidate, directory):
        raise DataValidationError("asset_path_escape: representation escapes asset directory")
    return candidate


def _normalized_suffix(suffix: str, format_: AssetFormat) -> str:
    normalized = suffix.lower()
    if format_ == AssetFormat.JPEG and normalized in {".jpeg", ".jpg"}:
        return normalized
    expected = _FORMAT_EXTENSIONS[format_]
    return expected if expected != ".bin" else normalized or expected


def _url_suffix(url: str) -> str:
    return Path(urlsplit(url).path).suffix.lower()
