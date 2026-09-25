"""Studio Protocol question and history methods."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from qbank.markdown_codec import parse_question_text
from qbank.models import (
    IngestOptions,
    Question,
    QuestionPatch,
)
from qbank.operations import ingest_questions_in_context
from qbank.studio_sidecar.errors import (
    INVALID_PARAMS,
    RpcError,
)
from qbank.studio_sidecar.session import (
    OpenRepository,
    StudioSession,
    object_value,
    optional_int,
    query_filters,
    question_patch,
    required_string,
    string_list,
    summary_hit,
)


class QuestionMethods(StudioSession):
    """Question and history Protocol methods."""

    def question_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        filters = query_filters(params)
        self._ensure_projection_current(opened)
        return [summary_hit(item) for item in opened.services.questions.index.query(filters)]

    def question_search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        text = required_string(params, "text")
        limit = optional_int(params, "limit", 100)
        self._ensure_projection_current(opened)
        return [
            summary_hit(item)
            for item in opened.services.questions.search_projection(text, limit=limit)
        ]

    def question_get(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = required_string(params, "id")
        record = opened.snapshot.locate(question_id)
        return {
            "question": record.question.model_dump(mode="json"),
            "source": record.text,
            "revision": opened.revision,
            "diagnostics": [],
        }

    def question_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        question_id = required_string(params, "id")
        source = required_string(params, "source", allow_empty=True)
        return self._validate_source(question_id, source)

    def question_save(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = required_string(params, "id")
        source = required_string(params, "source", allow_empty=True)
        current = self._require_current_revision(params, opened)
        validation = self._validate_source(question_id, source)
        if not validation["ok"]:
            return {
                **validation,
                "revision": current,
                "source": source,
                "indexUpdated": False,
            }
        candidate, _, _ = parse_question_text(source)
        previous = opened.snapshot.locate(question_id).question
        patch = question_patch(previous, candidate)
        dry_run = opened.services.studio.save_question(
            question_id,
            patch,
            dry_run=True,
            command="qbank studio protocol save",
        )
        if not dry_run.ok:
            diagnostics = [
                item.model_dump(mode="json", exclude_none=True)
                for item in [*dry_run.validation_errors, *dry_run.validation_warnings]
            ]
            return {
                "ok": False,
                "diagnostics": diagnostics,
                "canonicalChanged": validation["canonicalChanged"],
                "revision": current,
                "source": source,
                "indexUpdated": False,
            }
        result = opened.services.studio.save_question(
            question_id,
            patch,
            dry_run=False,
            command="qbank studio protocol save",
        )
        self._refresh_snapshot(opened)
        record = opened.snapshot.locate(question_id)
        return {
            "ok": result.ok,
            "diagnostics": [
                item.model_dump(mode="json", exclude_none=True)
                for item in [
                    *result.validation_errors,
                    *result.validation_warnings,
                    *result.warnings,
                ]
            ],
            "canonicalChanged": record.text != source,
            "revision": opened.revision,
            "source": record.text,
            "indexUpdated": result.index_updated,
        }

    def question_update(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply visible structured metadata through qbank's Studio transaction."""
        opened = self._opened()
        question_id = required_string(params, "id")
        self._require_current_revision(params, opened)
        previous = opened.snapshot.locate(question_id).question
        raw_set_value: object = params.get("set", {})
        if not isinstance(raw_set_value, dict):
            raise RpcError(INVALID_PARAMS, "set must be an object")
        raw_set = cast(dict[str, Any], raw_set_value)
        topics_value: object = params.get("topics", previous.topics)
        if not isinstance(topics_value, list):
            raise RpcError(INVALID_PARAMS, "topics must be an array of strings")
        topic_items = cast(list[object], topics_value)
        if not all(isinstance(item, str) for item in topic_items):
            raise RpcError(INVALID_PARAMS, "topics must be an array of strings")
        topics = cast(list[str], topic_items)
        patch = QuestionPatch(
            set=raw_set,
            add_topics=[item for item in topics if item not in previous.topics],
            remove_topics=[item for item in previous.topics if item not in topics],
        )
        return self._commit_question_patch(opened, question_id, patch, "metadata update")

    def question_create(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = required_string(params, "id")
        title = required_string(params, "title")
        dry_run = opened.services.studio_project.create_question(question_id, title, dry_run=True)
        result = opened.services.studio_project.create_question(question_id, title, dry_run=False)
        return self._question_mutation_result(opened, question_id, dry_run, result)

    def question_copy(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        source_id = required_string(params, "sourceId")
        new_id = required_string(params, "newId")
        dry_run = opened.services.studio_project.copy_question(source_id, new_id, dry_run=True)
        result = opened.services.studio_project.copy_question(source_id, new_id, dry_run=False)
        return self._question_mutation_result(opened, new_id, dry_run, result)

    def question_import(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = Path(required_string(params, "path")).expanduser().resolve(strict=True)
        if path.suffix.casefold() not in {".json", ".jsonl"} or not path.is_file():
            raise RpcError(INVALID_PARAMS, "import path must be a JSON or JSONL file")
        dry_run = opened.services.studio_project.import_questions(path, dry_run=True)
        if not dry_run.ok:
            return {
                "ok": False,
                "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
                "revision": opened.revision,
            }
        result = opened.services.studio_project.import_questions(path, dry_run=False)
        if result.ok:
            self._refresh_snapshot(opened)
        return {
            "ok": result.ok,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": opened.revision,
        }

    def question_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = required_string(params, "id")
        dry_run = opened.services.studio_project.delete_question(question_id, dry_run=True)
        result = opened.services.studio_project.delete_question(question_id, dry_run=False)
        if result.ok:
            self._refresh_snapshot(opened)
        return {
            "ok": result.ok,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": opened.revision,
        }

    def question_bulk_update(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_ids = string_list(params, "questionIds", allow_empty=False)
        raw_set = object_value(params, "set")
        allowed = {"status", "chapter"}
        if not raw_set or not set(raw_set).issubset(allowed):
            raise RpcError(
                INVALID_PARAMS,
                "set must contain only status and/or chapter",
            )
        questions: list[Question] = []
        for question_id in question_ids:
            previous = opened.snapshot.locate(question_id).question
            questions.append(
                Question.model_validate({**previous.model_dump(mode="json"), **raw_set})
            )
        options = IngestOptions(
            upsert=True,
            dry_run=True,
            command="qbank studio protocol question bulk update",
        )
        planned = ingest_questions_in_context(
            opened.context,
            questions,
            services=opened.services.mutations,
            options=options,
        )
        if not planned.ok:
            return {
                "ok": False,
                "dryRun": planned.model_dump(mode="json", exclude_none=True),
                "revision": opened.revision,
            }
        result = ingest_questions_in_context(
            opened.context,
            questions,
            services=opened.services.mutations,
            options=options.model_copy(update={"dry_run": False}),
        )
        revision = self._refresh_snapshot(opened) if result.ok else opened.revision
        return {
            "ok": result.ok,
            "dryRun": planned.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def history_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        question_id = required_string(params, "questionId")
        asset_events = opened.services.assets.history(question_id).events
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.history.timeline(question_id, asset_events)
        ]

    def _commit_question_patch(
        self,
        opened: OpenRepository,
        question_id: str,
        patch: QuestionPatch,
        operation: str,
    ) -> dict[str, Any]:
        dry_run = opened.services.studio.save_question(
            question_id,
            patch,
            dry_run=True,
            command=f"qbank studio protocol {operation}",
        )
        if not dry_run.ok:
            return {
                "ok": False,
                "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
                "revision": opened.revision,
            }
        result = opened.services.studio.save_question(
            question_id,
            patch,
            dry_run=False,
            command=f"qbank studio protocol {operation}",
        )
        self._refresh_snapshot(opened)
        record = opened.snapshot.locate(question_id)
        return {
            "ok": result.ok,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "question": record.question.model_dump(mode="json"),
            "source": record.text,
            "revision": opened.revision,
        }

    def _question_mutation_result(
        self,
        opened: OpenRepository,
        question_id: str,
        dry_run: Any,
        result: Any,
    ) -> dict[str, Any]:
        self._refresh_snapshot(opened)
        record = opened.snapshot.locate(question_id)
        return {
            "ok": result.ok,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "document": {
                "question": record.question.model_dump(mode="json"),
                "source": record.text,
                "revision": opened.revision,
                "diagnostics": [],
            },
        }
