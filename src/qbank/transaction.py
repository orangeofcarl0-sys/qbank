"""Crash-recoverable authoritative file transactions."""

from __future__ import annotations

import json
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.utils import atomic_write_bytes, atomic_write_text, reject_reparse_points


class _JournalEntry(TypedDict):
    path: str
    existed: bool
    backup: str | None


class _JournalManifest(TypedDict):
    format_version: int
    status: str
    entries: list[_JournalEntry]


def _write_plan() -> dict[Path, str]:
    return {}


def _byte_write_plan() -> dict[Path, bytes]:
    return {}


def _delete_plan() -> set[Path]:
    return set()


@dataclass
class MutationTransaction:
    """A precomputed file mutation with optional durable rollback journal."""

    writes: dict[Path, str] = field(default_factory=_write_plan)
    byte_writes: dict[Path, bytes] = field(default_factory=_byte_write_plan)
    deletes: set[Path] = field(default_factory=_delete_plan)
    repository_root: Path | None = None
    journal_directory: Path | None = None

    @classmethod
    def for_context(cls, context: ProjectContext) -> MutationTransaction:
        """Create a transaction recovered by the repository write lock."""
        return cls(
            repository_root=context.root,
            journal_directory=context.paths.state / "transactions",
        )

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
        """Commit all files and restore originals after exceptions or process crashes."""
        targets = sorted(
            {*self.writes, *self.byte_writes, *self.deletes},
            key=lambda path: str(path),
        )
        self._validate_targets(targets)
        snapshots: dict[Path, bytes | None] = {
            path: path.read_bytes() if path.exists() else None for path in targets
        }
        journal = self._prepare_journal(targets, snapshots)
        try:
            for path, text in self.writes.items():
                self._validate_targets([path])
                atomic_write_text(path, text)
            for path, content in self.byte_writes.items():
                self._validate_targets([path])
                atomic_write_bytes(path, content)
            for path in sorted(self.deletes, key=lambda item: str(item)):
                self._validate_targets([path])
                path.unlink(missing_ok=True)
        except Exception as original_error:
            failures = _restore_snapshots(targets, snapshots)
            for failure in failures:
                original_error.add_note(f"rollback failed: {failure}")
            if not failures:
                _remove_journal(journal)
            raise
        if journal is not None:
            _set_journal_status(journal, "committed")
            _remove_journal(journal)

    def _prepare_journal(
        self,
        targets: list[Path],
        snapshots: dict[Path, bytes | None],
    ) -> Path | None:
        if not targets or self.repository_root is None or self.journal_directory is None:
            return None
        root = self.repository_root.resolve()
        journal_root = self.journal_directory
        if journal_root.is_symlink():
            raise DataValidationError("transaction journal directory must not be a symbolic link")
        journal_root.mkdir(parents=True, exist_ok=True)
        journal = journal_root / f"{uuid.uuid4().hex}.txn"
        journal.mkdir()
        entries: list[_JournalEntry] = []
        try:
            for index, path in enumerate(targets):
                try:
                    reject_reparse_points(path, boundary=root)
                except ValueError as exc:
                    raise DataValidationError(
                        f"transaction target contains an unsupported reparse point: {path}"
                    ) from exc
                resolved = path.resolve(strict=False)
                try:
                    relative = resolved.relative_to(root).as_posix()
                except ValueError as exc:
                    raise DataValidationError(
                        f"transaction target escapes repository: {path}"
                    ) from exc
                original = snapshots[path]
                backup = None
                if original is not None:
                    backup = f"backup-{index:06d}.bin"
                    atomic_write_bytes(journal / backup, original)
                entries.append(
                    {
                        "path": relative,
                        "existed": original is not None,
                        "backup": backup,
                    }
                )
            manifest = {
                "format_version": 1,
                "status": "prepared",
                "entries": entries,
            }
            atomic_write_text(
                journal / "manifest.json",
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            )
        except Exception:
            shutil.rmtree(journal, ignore_errors=True)
            raise
        return journal

    def _validate_targets(self, targets: list[Path]) -> None:
        if self.repository_root is None:
            return
        root = self.repository_root.resolve()
        for path in targets:
            try:
                reject_reparse_points(path, boundary=root)
            except ValueError as exc:
                raise DataValidationError(
                    f"transaction target contains an unsupported reparse point: {path}"
                ) from exc
            if not path.resolve(strict=False).is_relative_to(root):
                raise DataValidationError(f"transaction target escapes repository: {path}")


def recover_pending_transactions(context: ProjectContext) -> int:
    """Rollback prepared journals and clean completed journals while holding the lock."""
    journal_root = context.paths.state / "transactions"
    if not journal_root.exists():
        return 0
    if journal_root.is_symlink() or not journal_root.is_dir():
        raise DataValidationError("transaction journal path is not a trusted directory")
    recovered = 0
    for journal in sorted(journal_root.iterdir(), key=lambda item: item.name):
        if journal.is_symlink() or not journal.is_dir():
            raise DataValidationError(f"invalid transaction journal entry: {journal.name}")
        manifest_path = journal / "manifest.json"
        if not manifest_path.is_file():
            _remove_journal(journal)
            continue
        manifest = _read_manifest(manifest_path)
        status = manifest.get("status")
        if status == "prepared":
            _restore_journal(context.root, journal, manifest)
            recovered += 1
        elif status != "committed":
            raise DataValidationError(f"invalid transaction journal status: {status}")
        _remove_journal(journal)
    with suppress(OSError):
        journal_root.rmdir()
    return recovered


def _read_manifest(path: Path) -> _JournalManifest:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataValidationError(f"invalid transaction journal: {path}") from exc
    if not isinstance(value, dict):
        raise DataValidationError(f"unsupported transaction journal: {path}")
    mapping = cast(dict[str, object], value)
    if mapping.get("format_version") != 1 or not isinstance(mapping.get("status"), str):
        raise DataValidationError(f"unsupported transaction journal: {path}")
    raw_entries = mapping.get("entries")
    if not isinstance(raw_entries, list):
        raise DataValidationError(f"invalid transaction journal entries: {path}")
    entries: list[_JournalEntry] = []
    for value in cast(list[object], raw_entries):
        if not isinstance(value, dict):
            raise DataValidationError(f"invalid transaction journal entry: {path}")
        raw = cast(dict[str, object], value)
        relative = raw.get("path")
        existed = raw.get("existed")
        backup = raw.get("backup")
        if (
            not isinstance(relative, str)
            or not isinstance(existed, bool)
            or (backup is not None and not isinstance(backup, str))
        ):
            raise DataValidationError(f"invalid transaction journal entry: {path}")
        entries.append({"path": relative, "existed": existed, "backup": backup})
    return {
        "format_version": 1,
        "status": cast(str, mapping["status"]),
        "entries": entries,
    }


def _restore_journal(root: Path, journal: Path, manifest: _JournalManifest) -> None:
    entries = manifest["entries"]
    resolved_root = root.resolve()
    for raw in reversed(entries):
        pure = PurePosixPath(raw["path"])
        if pure.is_absolute() or ".." in pure.parts:
            raise DataValidationError(f"transaction recovery path escapes repository: {pure}")
        target = resolved_root.joinpath(*pure.parts)
        try:
            reject_reparse_points(target, boundary=resolved_root)
        except ValueError as exc:
            raise DataValidationError(
                f"transaction recovery path contains a reparse point: {pure}"
            ) from exc
        if not target.resolve(strict=False).is_relative_to(resolved_root):
            raise DataValidationError(f"transaction recovery path escapes repository: {pure}")
        if raw["existed"]:
            backup_name = raw["backup"]
            if backup_name is None or Path(backup_name).name != backup_name:
                raise DataValidationError(f"invalid transaction backup: {journal}")
            atomic_write_bytes(target, (journal / backup_name).read_bytes())
        else:
            target.unlink(missing_ok=True)


def _restore_snapshots(
    targets: list[Path],
    snapshots: dict[Path, bytes | None],
) -> list[str]:
    failures: list[str] = []
    for path in reversed(targets):
        try:
            original = snapshots[path]
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, original)
        except Exception as error:
            failures.append(f"{path}: {error}")
    return failures


def _set_journal_status(journal: Path, status: str) -> None:
    manifest_path = journal / "manifest.json"
    manifest = _read_manifest(manifest_path)
    manifest["status"] = status
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )


def _remove_journal(journal: Path | None) -> None:
    if journal is not None:
        shutil.rmtree(journal, ignore_errors=False)
