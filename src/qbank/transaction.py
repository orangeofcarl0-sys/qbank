"""Rollback-capable authoritative Markdown and history mutations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from qbank.utils import atomic_write_bytes, atomic_write_text


def _write_plan() -> dict[Path, str]:
    return {}


def _byte_write_plan() -> dict[Path, bytes]:
    return {}


def _delete_plan() -> set[Path]:
    return set()


@dataclass
class MutationTransaction:
    """A precomputed set of authoritative file writes and deletions."""

    writes: dict[Path, str] = field(default_factory=_write_plan)
    byte_writes: dict[Path, bytes] = field(default_factory=_byte_write_plan)
    deletes: set[Path] = field(default_factory=_delete_plan)

    def write(self, path: Path, text: str) -> None:
        """Plan one UTF-8 file replacement."""
        self.writes[path] = text
        self.byte_writes.pop(path, None)
        self.deletes.discard(path)

    def write_bytes(self, path: Path, content: bytes) -> None:
        """Plan one binary file replacement."""
        self.byte_writes[path] = content
        self.writes.pop(path, None)
        self.deletes.discard(path)

    def delete(self, path: Path) -> None:
        """Plan one file deletion."""
        if path not in self.writes and path not in self.byte_writes:
            self.deletes.add(path)

    def commit(self) -> None:
        """Commit all files and restore their original bytes on any failure."""
        targets = sorted(
            {*self.writes, *self.byte_writes, *self.deletes},
            key=lambda path: str(path),
        )
        snapshots: dict[Path, bytes | None] = {
            path: path.read_bytes() if path.exists() else None for path in targets
        }
        try:
            for path in self.writes:
                atomic_write_text(path, self.writes[path])
            for path in self.byte_writes:
                atomic_write_bytes(path, self.byte_writes[path])
            for path in sorted(self.deletes, key=lambda item: str(item)):
                path.unlink(missing_ok=True)
        except Exception as original_error:
            rollback_failures: list[str] = []
            for path in reversed(targets):
                original_content = snapshots[path]
                try:
                    if original_content is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write_bytes(path, original_content)
                except Exception as rollback_error:
                    rollback_failures.append(f"{path}: {rollback_error}")
            for failure in rollback_failures:
                original_error.add_note(f"rollback failed: {failure}")
            raise
