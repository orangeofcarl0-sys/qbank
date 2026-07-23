"""In-memory, repository-revision-bound MCP prepare/commit operations."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeAlias

from pydantic import JsonValue

from qbank.errors import ConflictError, DataValidationError
from qbank.models import (
    IngestPrepareRequest,
    McpOperationResult,
    McpPrepareResult,
    PaperPrepareRequest,
    PatchPrepareRequest,
    TagChangePrepareRequest,
)

OperationPayload: TypeAlias = (
    IngestPrepareRequest | PatchPrepareRequest | TagChangePrepareRequest | PaperPrepareRequest
)


@dataclass(slots=True)
class PreparedOperation:
    """Internal payload and lifecycle for one reviewed operation."""

    preview: McpPrepareResult
    payload: OperationPayload
    committed_result: JsonValue | None = None
    committed_revision: str | None = None
    cancelled: bool = False


class OperationStore:
    """Coordinate optimistic commits and make repeat commits idempotent."""

    def __init__(
        self,
        revision: Callable[[], str],
        commit: Callable[[PreparedOperation], JsonValue],
        *,
        ttl: timedelta = timedelta(minutes=15),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._revision = revision
        self._commit = commit
        self._ttl = ttl
        self._now = now or (lambda: datetime.now(UTC))
        self._items: dict[str, PreparedOperation] = {}
        self._lock = threading.RLock()

    def add(
        self,
        payload: OperationPayload,
        preview: McpPrepareResult,
    ) -> McpPrepareResult:
        with self._lock:
            self._items[preview.operation_id] = PreparedOperation(preview, payload)
        return preview

    def identity(self) -> tuple[str, datetime]:
        """Create the operation identity and expiry used by one dry-run."""
        return uuid.uuid4().hex, self._now() + self._ttl

    def commit(self, operation_id: str, repository_revision: str) -> McpOperationResult:
        with self._lock:
            operation = self._require(operation_id)
            if operation.committed_result is not None:
                return McpOperationResult(
                    ok=True,
                    operation_id=operation_id,
                    status="committed",
                    repository_revision=operation.committed_revision or repository_revision,
                    result=operation.committed_result,
                    idempotent_replay=True,
                )
            self._require_active(operation)
            if repository_revision != operation.preview.repository_revision:
                raise ConflictError("repository revision does not match the prepared operation")
            current = self._revision()
            if current != operation.preview.repository_revision:
                raise ConflictError("repository changed after prepare; prepare the operation again")
            if not operation.preview.committable:
                raise DataValidationError("operation is not committable")
            result = self._commit(operation)
            operation.committed_result = result
            operation.committed_revision = self._revision()
            return McpOperationResult(
                ok=True,
                operation_id=operation_id,
                status="committed",
                repository_revision=operation.committed_revision,
                result=result,
            )

    def cancel(self, operation_id: str) -> McpOperationResult:
        with self._lock:
            operation = self._require(operation_id)
            if operation.committed_result is not None:
                raise ConflictError("committed operation cannot be cancelled")
            replay = operation.cancelled
            operation.cancelled = True
            return McpOperationResult(
                ok=True,
                operation_id=operation_id,
                status="cancelled",
                repository_revision=self._revision(),
                idempotent_replay=replay,
            )

    def _require(self, operation_id: str) -> PreparedOperation:
        try:
            return self._items[operation_id]
        except KeyError as exc:
            raise DataValidationError(f"unknown operation_id: {operation_id}") from exc

    def _require_active(self, operation: PreparedOperation) -> None:
        if operation.cancelled:
            raise ConflictError("operation has been cancelled")
        if self._now() >= operation.preview.expires_at:
            raise ConflictError("operation has expired; prepare it again")
