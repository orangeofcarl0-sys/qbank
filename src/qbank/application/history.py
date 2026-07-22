"""Unified Studio history assembled from question and asset authority logs."""

from __future__ import annotations

from dataclasses import dataclass

from qbank.application.ports import HistoryStorePort
from qbank.models import AssetHistoryEntry, DesktopHistoryEntry


@dataclass(frozen=True, slots=True)
class QuestionHistoryService:
    """Merge question and asset events into one deterministic timeline."""

    history: HistoryStorePort

    def timeline(
        self,
        question_id: str,
        asset_events: list[AssetHistoryEntry],
    ) -> list[DesktopHistoryEntry]:
        events = list(self.history.list(question_id))
        events.extend(self._asset_event(event) for event in asset_events)
        return sorted(events, key=lambda event: (event.timestamp, event.operation, event.source))

    @staticmethod
    def _asset_event(event: AssetHistoryEntry) -> DesktopHistoryEntry:
        fields = list(
            dict.fromkeys(
                str(change.get("field"))
                for change in event.changes
                if change.get("field") is not None
            )
        )
        if not fields:
            fields = list(event.representation_ids) or ["图形资产"]
        return DesktopHistoryEntry(
            timestamp=event.timestamp,
            operation=event.operation,
            question_id=event.question_id,
            asset_id=event.asset_id,
            source="图形资产",
            fields=fields,
            changes=event.changes,
        )
