"""Cross-process repository write lock with crash-safe operating-system ownership."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, cast

from qbank.application.locking import RepositoryLockHolder, RepositoryLockLease
from qbank.context import ProjectContext
from qbank.errors import DataValidationError, RepositoryLockedError
from qbank.transaction import recover_pending_transactions
from qbank.utils import atomic_write_text, is_reparse_point

_MUTEX_GUARD = threading.Lock()
_PROCESS_MUTEXES: dict[str, threading.RLock] = {}
_THREAD_STATE = threading.local()


def _process_mutex(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _MUTEX_GUARD:
        return _PROCESS_MUTEXES.setdefault(key, threading.RLock())


class RepositoryWriteLock:
    """Use a kernel lock for ownership and a JSON sidecar only for diagnostics."""

    def __init__(
        self,
        context: ProjectContext,
        *,
        default_timeout: float = 10.0,
        poll_interval: float = 0.05,
    ) -> None:
        self.root = context.root
        self.context = context
        self.state = context.paths.state
        self.guard_path = self.state / "repository.write.lock"
        self.metadata_path = self.state / "repository.write-lock.json"
        self.default_timeout = default_timeout
        self.poll_interval = poll_interval
        self._key = os.path.normcase(str(self.guard_path.resolve()))
        self._mutex = _process_mutex(self.guard_path)

    @contextmanager
    def hold(
        self,
        operation: str,
        *,
        timeout: float | None = None,
    ) -> Generator[RepositoryLockLease]:
        """Acquire the repository lock, supporting same-thread nested services."""
        wait = self.default_timeout if timeout is None else timeout
        if wait < 0:
            raise DataValidationError("repository lock timeout must be non-negative")
        with self._mutex:
            held = self._held_leases()
            existing = held.get(self._key)
            if existing is not None:
                lease, depth = existing
                held[self._key] = (lease, depth + 1)
                try:
                    yield lease
                finally:
                    held[self._key] = (lease, depth)
                return
            handle, lease = self._acquire(operation, wait)
            held[self._key] = (lease, 1)
            original: BaseException | None = None
            try:
                yield lease
            except BaseException as exc:
                original = exc
                raise
            finally:
                held.pop(self._key, None)
                try:
                    self._release(handle, lease)
                except Exception as release_error:
                    if original is not None:
                        original.add_note(f"repository lock release failed: {release_error}")
                    else:
                        raise

    def _acquire(self, operation: str, timeout: float) -> tuple[BinaryIO, RepositoryLockLease]:
        self.state.mkdir(parents=True, exist_ok=True)
        self._reject_symlinks()
        handle = self.guard_path.open("a+b")
        _ensure_lock_byte(handle)
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock_file(handle)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    handle.close()
                    holder = self._read_holder()
                    details: dict[str, object] = {
                        "repository": str(self.root),
                        "timeout_seconds": timeout,
                    }
                    if holder is not None:
                        details["holder"] = holder.as_dict()
                    raise RepositoryLockedError(
                        "repository_locked: timed out waiting for the repository write lock",
                        details=details,
                    ) from exc
                time.sleep(self.poll_interval)
        try:
            recover_pending_transactions(self.context)
        except Exception:
            _unlock_file(handle)
            handle.close()
            raise
        recovered = self._read_holder()
        holder = RepositoryLockHolder(
            token=uuid.uuid4().hex,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            operation=operation,
            command=" ".join(sys.argv),
            acquired_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        atomic_write_text(
            self.metadata_path,
            json.dumps(holder.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )
        return handle, RepositoryLockLease(holder=holder, recovered_holder=recovered)

    def _release(self, handle: BinaryIO, lease: RepositoryLockLease) -> None:
        try:
            current = self._read_holder()
            if current is not None and current.token == lease.holder.token:
                self.metadata_path.unlink(missing_ok=True)
        finally:
            try:
                _unlock_file(handle)
            finally:
                handle.close()

    def _read_holder(self) -> RepositoryLockHolder | None:
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            return RepositoryLockHolder(
                token=str(payload["token"]),
                pid=int(payload["pid"]),
                hostname=str(payload["hostname"]),
                operation=str(payload["operation"]),
                command=str(payload["command"]),
                acquired_at=str(payload["acquired_at"]),
            )
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            return None

    def _reject_symlinks(self) -> None:
        for path in (self.guard_path, self.metadata_path):
            if is_reparse_point(path):
                raise DataValidationError(
                    f"repository lock path must not be a reparse point: {path}"
                )

    def _held_leases(self) -> dict[str, tuple[RepositoryLockLease, int]]:
        value = getattr(_THREAD_STATE, "leases", None)
        if value is None:
            value = {}
            _THREAD_STATE.leases = value
        return cast(dict[str, tuple[RepositoryLockLease, int]], value)


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)


if os.name == "nt":
    import msvcrt

    def _lock_file(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock_file(handle: BinaryIO) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    _fcntl_attributes = vars(fcntl)
    _flock = cast(Callable[[int, int], None], _fcntl_attributes["flock"])
    _lock_ex = cast(int, _fcntl_attributes["LOCK_EX"])
    _lock_nb = cast(int, _fcntl_attributes["LOCK_NB"])
    _lock_un = cast(int, _fcntl_attributes["LOCK_UN"])

    def _lock_file(handle: BinaryIO) -> None:
        _flock(handle.fileno(), _lock_ex | _lock_nb)

    def _unlock_file(handle: BinaryIO) -> None:
        _flock(handle.fileno(), _lock_un)
