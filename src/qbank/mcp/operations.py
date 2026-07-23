"""Durable, repository-revision-bound MCP prepare/commit operations."""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, TypeAlias, cast

from pydantic import BaseModel, JsonValue

from qbank.application.locking import RepositoryLockLease, RepositoryWriteLockPort
from qbank.errors import (
    DataValidationError,
    OperationAlreadyCommittedError,
    OperationCancelledError,
    OperationExpiredError,
    RepositoryRevisionChangedError,
)
from qbank.models import (
    AssetIngestPrepareRequest,
    AssetPreferredPrepareRequest,
    AssetStatusPrepareRequest,
    IngestPrepareRequest,
    McpOperationResult,
    McpPrepareResult,
    PaperPrepareRequest,
    PatchPrepareRequest,
    TagChangePrepareRequest,
)
from qbank.utils import atomic_write_text

OperationPayload: TypeAlias = (
    IngestPrepareRequest
    | PatchPrepareRequest
    | TagChangePrepareRequest
    | PaperPrepareRequest
    | AssetIngestPrepareRequest
    | AssetStatusPrepareRequest
    | AssetPreferredPrepareRequest
)
OperationStatus: TypeAlias = Literal["prepared", "committing", "committed", "cancelled", "expired"]
_OPERATION_ID = re.compile(r"^[0-9a-f]{32}$")
_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "ingest": IngestPrepareRequest,
    "patch": PatchPrepareRequest,
    "tag_change": TagChangePrepareRequest,
    "paper": PaperPrepareRequest,
    "asset_ingest": AssetIngestPrepareRequest,
    "asset_status": AssetStatusPrepareRequest,
    "asset_preferred": AssetPreferredPrepareRequest,
}


@dataclass(slots=True)
class PreparedOperation:
    """Minimal durable intent and lifecycle for one reviewed operation."""

    preview: McpPrepareResult
    payload: OperationPayload
    status: OperationStatus = "prepared"
    created_at: datetime | None = None
    committed_result: JsonValue | None = None
    committed_revision: str | None = None
    verified_revision: str | None = None


class OperationStore:
    """Persist reviewed intent and make commits idempotent across process restarts."""

    def __init__(
        self,
        revision: Callable[[], str],
        commit: Callable[[PreparedOperation], JsonValue],
        *,
        directory: Path | None = None,
        lock: RepositoryWriteLockPort | None = None,
        ttl: timedelta = timedelta(minutes=15),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._revision = revision
        self._commit = commit
        self._directory = directory
        self._write_lock = lock
        self._ttl = ttl
        self._now = now or (lambda: datetime.now(UTC))
        self._items: dict[str, PreparedOperation] = {}
        self._thread_lock = threading.RLock()

    def add(
        self,
        payload: OperationPayload,
        preview: McpPrepareResult,
    ) -> McpPrepareResult:
        with self._thread_lock, self._hold("mcp_operation_prepare"):
            current = self._revision()
            if current != preview.repository_revision:
                raise RepositoryRevisionChangedError(
                    "repository_revision_changed: repository changed while preparing the operation",
                    details={"expected": preview.repository_revision, "current": current},
                )
            operation = PreparedOperation(
                preview=preview,
                payload=payload,
                created_at=self._now(),
            )
            if self._exists(preview.operation_id):
                raise DataValidationError(
                    f"schema_validation_failed: duplicate operation_id: {preview.operation_id}"
                )
            self._save(operation)
        return preview

    def identity(self) -> tuple[str, datetime]:
        """Create the operation identity and expiry used by one dry-run."""
        return uuid.uuid4().hex, self._now() + self._ttl

    def get(self, operation_id: str) -> McpOperationResult:
        with self._thread_lock, self._hold("mcp_operation_get"):
            operation = self._require(operation_id)
            self._expire_if_needed(operation)
            return self._result(operation_id, operation)

    def commit(self, operation_id: str, repository_revision: str) -> McpOperationResult:
        with self._thread_lock, self._hold("mcp_operation_commit"):
            operation = self._require(operation_id)
            if operation.status == "committed":
                replay = self._result(operation_id, operation, idempotent=True)
                replay.code = "operation_already_committed"
                return replay
            self._require_active(operation)
            if operation.status == "committing":
                self._recover_interrupted(operation)
            expected = operation.preview.repository_revision
            if repository_revision != expected:
                raise RepositoryRevisionChangedError(
                    "repository_revision_changed: revision does not match the prepared operation",
                    details={"expected": expected, "provided": repository_revision},
                )
            current = self._revision()
            if current != expected:
                raise RepositoryRevisionChangedError(
                    "repository_revision_changed: repository changed after prepare",
                    details={"expected": expected, "current": current},
                )
            if not operation.preview.committable:
                raise DataValidationError("schema_validation_failed: operation is not committable")
            operation.status = "committing"
            self._save(operation)
            operation.verified_revision = expected
            try:
                result = self._commit(operation)
            except Exception:
                if self._revision() == expected:
                    operation.status = "prepared"
                    self._save(operation)
                raise
            finally:
                operation.verified_revision = None
            operation.committed_result = result
            operation.committed_revision = self._revision()
            operation.status = "committed"
            self._save(operation)
            return self._result(operation_id, operation)

    def cancel(self, operation_id: str) -> McpOperationResult:
        with self._thread_lock, self._hold("mcp_operation_cancel"):
            operation = self._require(operation_id)
            if operation.status == "committed":
                raise OperationAlreadyCommittedError(
                    "operation_already_committed: committed operation cannot be cancelled",
                    details={"operation_id": operation_id},
                )
            if operation.status == "expired":
                raise OperationExpiredError(
                    "operation_expired: operation has expired",
                    details={"operation_id": operation_id},
                )
            replay = operation.status == "cancelled"
            operation.status = "cancelled"
            self._save(operation)
            return self._result(operation_id, operation, idempotent=replay)

    def _require(self, operation_id: str) -> PreparedOperation:
        operation = self._load(operation_id)
        if operation is None:
            raise DataValidationError(
                f"schema_validation_failed: unknown operation_id: {operation_id}"
            )
        return operation

    def _require_active(self, operation: PreparedOperation) -> None:
        self._expire_if_needed(operation)
        if operation.status == "cancelled":
            raise OperationCancelledError(
                "operation_cancelled: operation has been cancelled",
                details={"operation_id": operation.preview.operation_id},
            )
        if operation.status == "expired":
            raise OperationExpiredError(
                "operation_expired: operation has expired; prepare it again",
                details={
                    "operation_id": operation.preview.operation_id,
                    "expires_at": operation.preview.expires_at.isoformat(),
                },
            )

    def _expire_if_needed(self, operation: PreparedOperation) -> None:
        if operation.status in {"prepared", "committing"} and (
            self._now() >= operation.preview.expires_at
        ):
            operation.status = "expired"
            self._save(operation)

    def _recover_interrupted(self, operation: PreparedOperation) -> None:
        current = self._revision()
        expected = operation.preview.repository_revision
        if current == expected:
            operation.status = "prepared"
            self._save(operation)
            return
        raise RepositoryRevisionChangedError(
            "repository_revision_changed: interrupted commit requires inspection",
            details={
                "operation_id": operation.preview.operation_id,
                "status": "committing",
                "expected": expected,
                "current": current,
            },
        )

    def _result(
        self,
        operation_id: str,
        operation: PreparedOperation,
        *,
        idempotent: bool = False,
    ) -> McpOperationResult:
        return McpOperationResult(
            ok=True,
            operation_id=operation_id,
            status=operation.status,
            operation=operation.preview.operation,
            expires_at=operation.preview.expires_at,
            repository_revision=(
                operation.committed_revision or operation.preview.repository_revision
            ),
            result=operation.committed_result,
            idempotent_replay=idempotent,
        )

    def _save(self, operation: PreparedOperation) -> None:
        operation_id = operation.preview.operation_id
        self._items[operation_id] = operation
        if self._directory is None:
            return
        path = self._path(operation_id)
        self._ensure_directory()
        if path.is_symlink():
            raise DataValidationError(f"symbolic MCP operation file is not supported: {path}")
        payload = {
            "format_version": 1,
            "operation_id": operation_id,
            "operation": operation.preview.operation,
            "status": operation.status,
            "created_at": (operation.created_at or self._now()).isoformat(),
            "expires_at": operation.preview.expires_at.isoformat(),
            "repository_revision": operation.preview.repository_revision,
            "committable": operation.preview.committable,
            "payload": operation.payload.model_dump(mode="json", exclude_none=True),
            "committed_revision": operation.committed_revision,
            "committed_result": operation.committed_result,
        }
        atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )

    def _load(self, operation_id: str) -> PreparedOperation | None:
        if self._directory is None:
            return self._items.get(operation_id)
        path = self._path(operation_id)
        if not path.is_file():
            return None
        if path.is_symlink():
            raise DataValidationError(f"symbolic MCP operation file is not supported: {path}")
        try:
            raw = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
            operation_name = str(raw["operation"])
            model = _PAYLOAD_MODELS[operation_name]
            payload = cast(OperationPayload, model.model_validate(raw["payload"]))
            preview = McpPrepareResult.model_validate(
                {
                    "ok": bool(raw["committable"]),
                    "operation_id": operation_id,
                    "operation": operation_name,
                    "affected_objects": [],
                    "diff": [],
                    "validation": {"ok": bool(raw["committable"]), "diagnostics": []},
                    "repository_revision": raw["repository_revision"],
                    "committable": raw["committable"],
                    "expires_at": raw["expires_at"],
                }
            )
            operation = PreparedOperation(
                preview=preview,
                payload=payload,
                status=cast(OperationStatus, raw["status"]),
                created_at=datetime.fromisoformat(str(raw["created_at"])),
                committed_result=cast(JsonValue | None, raw.get("committed_result")),
                committed_revision=cast(str | None, raw.get("committed_revision")),
            )
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            raise DataValidationError(
                f"schema_validation_failed: invalid MCP operation file: {path.name}: {exc}"
            ) from exc
        self._items[operation_id] = operation
        return operation

    def _exists(self, operation_id: str) -> bool:
        if operation_id in self._items:
            return True
        return self._directory is not None and self._path(operation_id).exists()

    def _path(self, operation_id: str) -> Path:
        if _OPERATION_ID.fullmatch(operation_id) is None:
            raise DataValidationError(
                f"schema_validation_failed: invalid operation_id: {operation_id}"
            )
        if self._directory is None:
            raise RuntimeError("in-memory operation store has no path")
        return self._directory / f"{operation_id}.json"

    def _ensure_directory(self) -> None:
        if self._directory is None:
            return
        if self._directory.is_symlink():
            raise DataValidationError(
                f"symbolic MCP operation directory is not supported: {self._directory}"
            )
        self._directory.mkdir(parents=True, exist_ok=True)

    def _hold(self, operation: str) -> AbstractContextManager[RepositoryLockLease | None]:
        if self._write_lock is None:
            return nullcontext()
        return self._write_lock.hold(operation)
