"""Studio Protocol taxonomy methods."""

from __future__ import annotations

from functools import partial
from typing import Any, Literal

from qbank.models import (
    TaxonomyTag,
)
from qbank.studio_sidecar.errors import (
    INVALID_PARAMS,
    RpcError,
)
from qbank.studio_sidecar.session import (
    StudioSession,
    optional_int,
    optional_string,
    optional_string_list,
    required_string,
    string_list,
)


class TaxonomyMethods(StudioSession):
    """Taxonomy Protocol methods."""

    def taxonomy_list(self, _params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.tags.list_tags()
        ]

    def taxonomy_suggest(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        text = optional_string(params, "text", default="")
        limit = optional_int(params, "limit", 20)
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.tags.suggestions(text, limit=limit)
        ]

    def taxonomy_overview(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        top_n = optional_int(params, "topN", 20)
        return opened.services.tags.overview(top_n=top_n).model_dump(mode="json", exclude_none=True)

    def taxonomy_update(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        raw_tag = params.get("tag")
        if not isinstance(raw_tag, dict):
            raise RpcError(INVALID_PARAMS, "tag must be an object")
        tag = TaxonomyTag.model_validate(raw_tag)
        command = "qbank studio protocol taxonomy update"
        planned = opened.services.tags.update_tag(tag, dry_run=True, command=command)
        result = opened.services.tags.update_tag(tag, dry_run=False, command=command)
        revision = self._refresh_snapshot(opened)
        return {
            "ok": result.ok,
            "dryRun": planned.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def taxonomy_rename(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._taxonomy_relation_mutation("rename", params)

    def taxonomy_merge(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._taxonomy_relation_mutation("merge", params)

    def taxonomy_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._taxonomy_relation_mutation("delete", params)

    def taxonomy_bulk_edit(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_ids = string_list(params, "questionIds", allow_empty=False)
        additions = optional_string_list(params, "add")
        removals = optional_string_list(params, "remove")
        command = "qbank studio protocol taxonomy bulk edit"
        planned = opened.services.tags.bulk_edit(
            question_ids,
            add=additions,
            remove=removals,
            dry_run=True,
            command=command,
        )
        result = opened.services.tags.bulk_edit(
            question_ids,
            add=additions,
            remove=removals,
            dry_run=False,
            command=command,
        )
        revision = self._refresh_snapshot(opened)
        return {
            "ok": result.ok,
            "dryRun": planned.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def _taxonomy_relation_mutation(
        self, action: Literal["rename", "merge", "delete"], params: dict[str, Any]
    ) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        service = opened.services.tags
        command = f"qbank studio protocol taxonomy {action}"
        if action == "rename":
            old = required_string(params, "old")
            new = required_string(params, "new")
            call = partial(service.rename, old, new, command=command)
        elif action == "merge":
            source = required_string(params, "source")
            target = required_string(params, "target")
            call = partial(service.merge, source, target, command=command)
        else:
            value = required_string(params, "value")
            call = partial(service.delete, value, command=command)
        planned = call(dry_run=True)
        result = call(dry_run=False)
        revision = self._refresh_snapshot(opened)
        return {
            "ok": result.ok,
            "dryRun": planned.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }
