"""Studio Protocol saved-view methods."""

from __future__ import annotations

from typing import Any

from qbank.models import (
    QueryFilters,
)
from qbank.studio_sidecar.session import (
    StudioSession,
    object_value,
    query_filters,
    required_string,
    summary_hit,
)


class ViewMethods(StudioSession):
    """Saved-view Protocol methods."""

    def view_list(self, _params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.views.list_views()
        ]

    def view_save(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        name = required_string(params, "name")
        filters = query_filters(object_value(params, "filters"))
        planned = opened.services.views.save(name, filters, dry_run=True)
        result = opened.services.views.save(name, filters, dry_run=False)
        revision = self._refresh_revision(opened)
        return {
            "ok": result.ok,
            "dryRun": planned.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def view_rename(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        old = required_string(params, "old")
        new = required_string(params, "new")
        planned = opened.services.views.rename(old, new, dry_run=True)
        result = opened.services.views.rename(old, new, dry_run=False)
        revision = self._refresh_revision(opened)
        return {
            "ok": result.ok,
            "dryRun": planned.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def view_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        name = required_string(params, "name")
        planned = opened.services.views.delete(name, dry_run=True)
        result = opened.services.views.delete(name, dry_run=False)
        revision = self._refresh_revision(opened)
        return {
            "ok": result.ok,
            "dryRun": planned.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def view_apply(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        name = required_string(params, "name")
        questions = opened.services.views.apply(name)
        self._ensure_projection_current(opened)
        by_id = {
            item.id: item
            for item in opened.services.questions.index.query(
                QueryFilters(limit=max(1, len(opened.snapshot.records)))
            )
        }
        return [summary_hit(by_id[item.id]) for item in questions if item.id in by_id]
