"""Append-only mutation history records."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from qbank.context import ProjectContext
from qbank.domain import HistoryRecord
from qbank.utils import utc_now


class JsonHistoryStore:
    """Filesystem history implementation used by mutation transactions."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def prepare(self, record: HistoryRecord) -> tuple[Path, str]:
        """Prepare one append-only JSON history document without writing it."""
        return prepare_history(self.context, record)


def prepare_history(
    context: ProjectContext,
    record: HistoryRecord,
) -> tuple[Path, str]:
    """Prepare a history path and serialized record without writing it."""
    timestamp = utc_now()
    payload = {
        "timestamp": timestamp,
        "operation": record.operation,
        "question_ids": list(record.question_ids),
        "command": record.command,
        "dry_run": record.dry_run,
        "before_hash": record.before_hash,
        "after_hash": record.after_hash,
        "changes": list(record.changes),
    }
    compact_time = timestamp.replace(":", "").replace("-", "")
    path = (
        context.paths.state
        / "history"
        / (f"{compact_time}-{record.operation}-{uuid.uuid4().hex[:8]}.json")
    )
    return path, json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    ) + "\n"
