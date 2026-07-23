"""Application-facing repository write-lock contract."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RepositoryLockHolder:
    """Publicly diagnosable identity for one write-lock owner."""

    token: str
    pid: int
    hostname: str
    operation: str
    command: str
    acquired_at: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "token": self.token,
            "pid": self.pid,
            "hostname": self.hostname,
            "operation": self.operation,
            "command": self.command,
            "acquired_at": self.acquired_at,
        }


@dataclass(frozen=True, slots=True)
class RepositoryLockLease:
    """One acquired lease and optional metadata recovered after a crash."""

    holder: RepositoryLockHolder
    recovered_holder: RepositoryLockHolder | None = None


class RepositoryWriteLockPort(Protocol):
    """Serialize authoritative writes across processes and local interfaces."""

    def hold(
        self,
        operation: str,
        *,
        timeout: float | None = None,
    ) -> AbstractContextManager[RepositoryLockLease]: ...
