"""Append-only mutation history records."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, cast

from qbank.context import ProjectContext
from qbank.domain import HistoryRecord
from qbank.errors import DataValidationError
from qbank.models import DesktopHistoryEntry
from qbank.utils import utc_now


class JsonHistoryStore:
    """Filesystem history implementation used by mutation transactions."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def prepare(self, record: HistoryRecord) -> tuple[Path, str]:
        """Prepare one append-only JSON history document without writing it."""
        return prepare_history(self.context, record)

    def list(self, question_id: str) -> tuple[DesktopHistoryEntry, ...]:
        """Read normalized events for one question without creating state."""
        root = self.context.paths.state / "history"
        if not root.is_dir():
            return ()
        events: list[DesktopHistoryEntry] = []
        for path in sorted(root.glob("*.json")):
            try:
                payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
                question_ids = [str(value) for value in payload.get("question_ids", [])]
                if question_id not in question_ids:
                    continue
                changes = [
                    cast(dict[str, Any], change)
                    for change in payload.get("changes", [])
                    if isinstance(change, dict)
                ]
                events.append(_history_entry(question_id, payload, changes))
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                raise DataValidationError(f"invalid history record {path.name}: {exc}") from exc
        return tuple(events)


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


def _history_entry(
    question_id: str,
    payload: dict[str, Any],
    changes: list[dict[str, Any]],
) -> DesktopHistoryEntry:
    fields: list[str] = []
    for change in changes:
        field = change.get("field")
        kind = change.get("kind")
        if field is not None:
            fields.append("题目" if field == "*" else str(field))
        elif kind == "question_topics":
            fields.append("标签")
        elif kind in {"taxonomy", "taxonomy_pending"}:
            fields.append("标签登记")
    command = str(payload.get("command") or "未知来源")
    return DesktopHistoryEntry(
        timestamp=str(payload.get("timestamp") or ""),
        operation=str(payload.get("operation") or "unknown"),
        question_id=question_id,
        source="Studio" if "desktop" in command.casefold() else command,
        fields=list(dict.fromkeys(fields)) or ["题目"],
        changes=changes,
    )
