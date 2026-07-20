"""Domain contract for one durable mutation-history entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """All fields committed beside one authoritative mutation."""

    operation: str
    question_ids: tuple[str, ...]
    command: str
    dry_run: bool
    before_hash: str | None
    after_hash: str | None
    changes: tuple[dict[str, Any], ...]
