"""Small shared utilities."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def utc_now() -> str:
    """Return a second-precision UTC ISO 8601 timestamp."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_text(data: Any, *, indent: int | None = 2) -> str:
    """Serialize JSON consistently for humans and machines."""
    if isinstance(data, BaseModel):
        data = data.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )

    def default(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
        return str(value)

    return json.dumps(data, ensure_ascii=False, indent=indent, default=default)


def sha256_text(text: str | None) -> str | None:
    """Hash text when present."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace a UTF-8 text file in its destination directory."""
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Atomically replace a file with bytes staged in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether *path* resolves under *parent*."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def is_reparse_point(path: Path) -> bool:
    """Return whether an existing path is a symlink or Windows reparse point."""
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return path.is_symlink() or bool(attributes & 0x400)


def reject_reparse_points(path: Path, *, boundary: Path) -> None:
    """Reject existing reparse components below a trusted resolved boundary."""
    base = boundary.resolve()
    candidate = path.absolute()
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escapes boundary: {path}") from exc
    current = base
    for part in relative.parts:
        current /= part
        if is_reparse_point(current):
            raise ValueError(f"reparse point is not supported: {current}")
