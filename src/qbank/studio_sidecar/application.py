"""Studio Protocol adapter over shared qbank application services."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import platform
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from qbank import __version__ as qbank_version
from qbank.application.revision import (
    question_projection_revision,
    repository_revision,
)
from qbank.asset_references import classify_resource_uri
from qbank.assets import AssetService, stable_legacy_asset_id
from qbank.bootstrap import ProjectServices, create_project_services
from qbank.context import ProjectContext
from qbank.diagnostics import DiagnosticServices, project_status_in_context
from qbank.domain import RepositorySnapshot
from qbank.errors import (
    ConflictError,
    DataValidationError,
    MarkdownParseError,
    QBankError,
    RepositoryLockedError,
)
from qbank.markdown_codec import parse_question_text, render_question
from qbank.models import (
    QUESTION_PATCHABLE_FIELDS,
    AssetFormat,
    AssetPackage,
    AssetPackageRepresentation,
    AssetStatus,
    DesktopAssetItem,
    IngestOptions,
    Paper,
    PaperBuildOptions,
    PaperBuildRequest,
    QueryFilters,
    Question,
    QuestionPatch,
    SearchHit,
    TaxonomyTag,
)
from qbank.operations import ingest_questions_in_context
from qbank.papers import load_paper
from qbank.studio_operations import StudioProjectAdapter
from qbank.studio_sidecar import PROTOCOL_VERSION, __version__
from qbank.studio_sidecar.errors import (
    APPLICATION_ERROR,
    CONFLICT,
    INVALID_PARAMS,
    LOCKED,
    METHOD_NOT_FOUND,
    REPOSITORY_NOT_OPEN,
    VALIDATION,
    RpcError,
)
from qbank.studio_sidecar.ipe_bridge import with_unicode_safe_assets
from qbank.utils import is_reparse_point

LOGGER = logging.getLogger("qbank-studio-sidecar")
_MEDIA_FORMATS = {
    "image/png": AssetFormat.PNG,
    "image/jpeg": AssetFormat.JPEG,
    "image/svg+xml": AssetFormat.SVG,
    "image/webp": AssetFormat.WEBP,
    "application/pdf": AssetFormat.PDF,
    "application/x-ipe": AssetFormat.IPE,
}
_MACRO_NAME = re.compile(r"^[A-Za-z@]+$")
_MACRO_REFERENCE = re.compile(r"\\([A-Za-z@]+)")


@dataclass(slots=True)
class OpenRepository:
    context: ProjectContext
    services: ProjectServices
    snapshot: RepositorySnapshot
    revision: str
    projection_revision: str


@dataclass(frozen=True, slots=True)
class SnapshotQuestionRepository:
    """Expose one session snapshot through qbank's read-only repository port."""

    snapshot: RepositorySnapshot

    def scan(self) -> RepositorySnapshot:
        return self.snapshot


@dataclass(frozen=True, slots=True)
class AssetEditGuard:
    """Session-local proof that only one externally edited source changed."""

    revision: str
    source: Path
    source_hash: str
    other_files: tuple[tuple[str, str], ...]


class StudioApplication:
    """Stateful repository session with a narrow protocol-facing API."""

    def __init__(self) -> None:
        self.repository: OpenRepository | None = None
        self.shutdown_requested = False
        self._asset_edit_guards: dict[tuple[str, str], AssetEditGuard] = {}
        self._methods: dict[str, Callable[[dict[str, Any]], Any]] = {
            "initialize": self.initialize,
            "repository.open": self.repository_open,
            "repository.rebuildIndex": self.repository_rebuild_index,
            "repository.status": self.repository_status,
            "question.search": self.question_search,
            "question.list": self.question_list,
            "question.get": self.question_get,
            "question.validate": self.question_validate,
            "question.save": self.question_save,
            "question.update": self.question_update,
            "question.create": self.question_create,
            "question.copy": self.question_copy,
            "question.import": self.question_import,
            "question.delete": self.question_delete,
            "taxonomy.list": self.taxonomy_list,
            "taxonomy.suggest": self.taxonomy_suggest,
            "taxonomy.overview": self.taxonomy_overview,
            "taxonomy.update": self.taxonomy_update,
            "taxonomy.rename": self.taxonomy_rename,
            "taxonomy.merge": self.taxonomy_merge,
            "taxonomy.delete": self.taxonomy_delete,
            "taxonomy.bulkEdit": self.taxonomy_bulk_edit,
            "view.list": self.view_list,
            "view.save": self.view_save,
            "view.rename": self.view_rename,
            "view.delete": self.view_delete,
            "view.apply": self.view_apply,
            "question.bulkUpdate": self.question_bulk_update,
            "asset.list": self.asset_list,
            "asset.open": self.asset_open,
            "asset.create": self.asset_create,
            "asset.replace": self.asset_replace,
            "asset.render": self.asset_render,
            "asset.reconcile": self.asset_reconcile,
            "history.list": self.history_list,
            "paper.list": self.paper_list,
            "paper.get": self.paper_get,
            "paper.create": self.paper_create,
            "paper.save": self.paper_save,
            "paper.addQuestions": self.paper_add_questions,
            "paper.validate": self.paper_validate,
            "paper.build": self.paper_build,
            "application.shutdown": self.application_shutdown,
        }

    def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handler = self._methods.get(method)
        if handler is None:
            raise RpcError(METHOD_NOT_FOUND, f"unknown Studio Protocol method: {method}")
        try:
            return handler(params)
        except RpcError:
            raise
        except RepositoryLockedError as exc:
            raise RpcError(LOCKED, str(exc), getattr(exc, "details", None)) from exc
        except ConflictError as exc:
            raise RpcError(CONFLICT, str(exc)) from exc
        except (MarkdownParseError, DataValidationError, ValidationError) as exc:
            raise RpcError(VALIDATION, str(exc)) from exc
        except QBankError as exc:
            message = str(exc)
            code = LOCKED if "lock" in message.casefold() else APPLICATION_ERROR
            raise RpcError(code, message) from exc
        except (OSError, ValueError) as exc:
            raise RpcError(APPLICATION_ERROR, str(exc)) from exc

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        studio_version = _optional_string(params, "studioVersion", default="0.3.0-beta.2")
        return {
            "studioVersion": studio_version,
            "sidecarVersion": __version__,
            "coreVersion": qbank_version,
            "protocolVersion": PROTOCOL_VERSION,
            "schemaVersions": {"question": "1.0", "asset": "1.0", "paper": "1.0"},
            "capabilities": sorted(self._methods),
            "runtime": {
                "python": platform.python_version(),
                "transport": "json-rpc-2.0-over-stdio-lines",
            },
        }

    def repository_open(self, params: dict[str, Any]) -> dict[str, Any]:
        candidate = self._repository_candidate(_required_string(params, "root"))
        result = self._repository_open_result(candidate)
        self.repository = candidate
        self._asset_edit_guards.clear()
        return result

    def repository_rebuild_index(self, params: dict[str, Any]) -> dict[str, Any]:
        candidate = self._repository_candidate(_required_string(params, "root"))
        indexed = candidate.services.questions.rebuild_index()
        self._refresh_snapshot(candidate)
        result = self._repository_open_result(candidate)
        self.repository = candidate
        self._asset_edit_guards.clear()
        return {**result, "indexed": indexed}

    def _repository_candidate(self, raw_root: str) -> OpenRepository:
        root = Path(raw_root).expanduser().resolve(strict=True)
        if not (root / "qbank.yaml").is_file():
            raise RpcError(INVALID_PARAMS, "selected directory is not a qbank repository")
        context = ProjectContext.from_root(root)
        services = with_unicode_safe_assets(context, create_project_services(context))
        return OpenRepository(
            context=context,
            services=services,
            snapshot=services.repository.scan(),
            revision=repository_revision(context),
            projection_revision=question_projection_revision(context),
        )

    def _repository_open_result(self, opened: OpenRepository) -> dict[str, Any]:
        try:
            self._ensure_projection_current(opened)
            questions = [
                _summary_hit(item)
                for item in opened.services.questions.index.query(
                    QueryFilters(offset=0, limit=20_000)
                )
            ]
        except DataValidationError as exc:
            diagnostic = str(exc).partition(":")[0]
            raise RpcError(
                VALIDATION,
                str(exc),
                {
                    "diagnosticCode": diagnostic,
                    "canRebuildIndex": diagnostic
                    in {"index_dirty", "index_stale", "index_unavailable"},
                },
            ) from exc
        tags = [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.tags.list_tags()
        ]
        views = [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.views.list_views()
        ]
        return {
            **self._repository_status(opened),
            "questions": questions,
            "tags": tags,
            "views": views,
        }

    def repository_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._synchronize_snapshot(opened)
        return self._repository_status(opened)

    def _repository_status(self, opened: OpenRepository) -> dict[str, Any]:
        diagnostics = DiagnosticServices(
            repository=SnapshotQuestionRepository(opened.snapshot),
            validator=opened.services.diagnostics.validator,
            index=opened.services.diagnostics.index,
        )
        status = project_status_in_context(opened.context, diagnostics)
        macros, studio_warnings = _load_studio_math(opened.context)
        return {
            "root": status.root,
            "name": opened.context.root.name,
            "revision": opened.revision,
            "healthy": status.invalid == 0 and not status.index_dirty,
            "questionCount": status.questions,
            "validationErrors": status.validation_errors,
            "indexDirty": status.index_dirty,
            "byStatus": status.by_status,
            "bySubject": status.by_subject,
            "mathMacros": macros,
            "studioWarnings": studio_warnings,
        }

    def question_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        filters = _query_filters(params)
        self._ensure_projection_current(opened)
        return [_summary_hit(item) for item in opened.services.questions.index.query(filters)]

    def question_search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        text = _required_string(params, "text")
        limit = _optional_int(params, "limit", 100)
        self._ensure_projection_current(opened)
        return [
            _summary_hit(item)
            for item in opened.services.questions.search_projection(text, limit=limit)
        ]

    def question_get(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = _required_string(params, "id")
        record = opened.snapshot.locate(question_id)
        return {
            "question": record.question.model_dump(mode="json"),
            "source": record.text,
            "revision": opened.revision,
            "diagnostics": [],
        }

    def question_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        question_id = _required_string(params, "id")
        source = _required_string(params, "source", allow_empty=True)
        return self._validate_source(question_id, source)

    def question_save(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = _required_string(params, "id")
        source = _required_string(params, "source", allow_empty=True)
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
        patch = _question_patch(previous, candidate)
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
        question_id = _required_string(params, "id")
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
        question_id = _required_string(params, "id")
        title = _required_string(params, "title")
        dry_run = opened.services.studio_project.create_question(question_id, title, dry_run=True)
        result = opened.services.studio_project.create_question(question_id, title, dry_run=False)
        return self._question_mutation_result(opened, question_id, dry_run, result)

    def question_copy(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        source_id = _required_string(params, "sourceId")
        new_id = _required_string(params, "newId")
        dry_run = opened.services.studio_project.copy_question(source_id, new_id, dry_run=True)
        result = opened.services.studio_project.copy_question(source_id, new_id, dry_run=False)
        return self._question_mutation_result(opened, new_id, dry_run, result)

    def question_import(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = Path(_required_string(params, "path")).expanduser().resolve(strict=True)
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
        question_id = _required_string(params, "id")
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

    def taxonomy_list(self, _params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.tags.list_tags()
        ]

    def taxonomy_suggest(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        text = _optional_string(params, "text", default="")
        limit = _optional_int(params, "limit", 20)
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.tags.suggestions(text, limit=limit)
        ]

    def taxonomy_overview(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        top_n = _optional_int(params, "topN", 20)
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
        question_ids = _string_list(params, "questionIds", allow_empty=False)
        additions = _optional_string_list(params, "add")
        removals = _optional_string_list(params, "remove")
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

    def view_list(self, _params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.views.list_views()
        ]

    def view_save(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        name = _required_string(params, "name")
        filters = _query_filters(_object_value(params, "filters"))
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
        old = _required_string(params, "old")
        new = _required_string(params, "new")
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
        name = _required_string(params, "name")
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
        name = _required_string(params, "name")
        questions = opened.services.views.apply(name)
        self._ensure_projection_current(opened)
        by_id = {
            item.id: item
            for item in opened.services.questions.index.query(
                QueryFilters(limit=max(1, len(opened.snapshot.records)))
            )
        }
        return [_summary_hit(by_id[item.id]) for item in questions if item.id in by_id]

    def question_bulk_update(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_ids = _string_list(params, "questionIds", allow_empty=False)
        raw_set = _object_value(params, "set")
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

    def _taxonomy_relation_mutation(
        self, action: Literal["rename", "merge", "delete"], params: dict[str, Any]
    ) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        service = opened.services.tags
        command = f"qbank studio protocol taxonomy {action}"
        if action == "rename":
            old = _required_string(params, "old")
            new = _required_string(params, "new")
            call = partial(service.rename, old, new, command=command)
        elif action == "merge":
            source = _required_string(params, "source")
            target = _required_string(params, "target")
            call = partial(service.merge, source, target, command=command)
        else:
            value = _required_string(params, "value")
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

    def asset_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        question_id = _required_string(params, "questionId")
        question = opened.snapshot.locate(question_id).question
        manifests = opened.services.assets.list_assets(question_id).assets
        history = opened.services.assets.history(question_id).events
        inventory = AssetService(opened.context, opened.services.assets)
        return [
            self._asset_item(opened, item)
            for item in inventory.desktop_items(question, manifests, history)
        ]

    def asset_open(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = _required_string(params, "questionId")
        reference = _optional_string(params, "reference", default="")
        if reference:
            return self._open_asset_reference(opened, question_id, reference, params)
        asset_id = _required_string(params, "assetId")
        action = _optional_string(params, "action", default="open")
        actions = {
            "open": opened.services.assets.open_asset,
            "original": opened.services.assets.open_original,
            "edit_ipe": opened.services.assets.begin_edit_session,
            "reveal": opened.services.assets.open_asset_directory,
        }
        handler = actions.get(action)
        if handler is None:
            raise RpcError(INVALID_PARAMS, f"unsupported asset open action: {action}")
        if action == "edit_ipe":
            self._require_current_revision(params, opened)
        dry_run = handler(question_id, asset_id, dry_run=True)
        result = handler(question_id, asset_id, dry_run=False)
        revision = self._refresh_revision(opened)
        if action == "edit_ipe":
            self._record_asset_edit_guard(opened, question_id, asset_id, revision)
        return {
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": revision,
        }

    def _open_asset_reference(
        self,
        opened: OpenRepository,
        question_id: str,
        reference: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        action = _optional_string(params, "action", default="open_reference")
        if action not in {"open_reference", "reveal_reference"}:
            raise RpcError(INVALID_PARAMS, f"unsupported resource open action: {action}")
        question = opened.snapshot.locate(question_id).question
        manifests = opened.services.assets.list_assets(question_id).assets
        history = opened.services.assets.history(question_id).events
        inventory = AssetService(opened.context, opened.services.assets)
        item = next(
            (
                candidate
                for candidate in inventory.desktop_items(question, manifests, history)
                if candidate.reference == reference
            ),
            None,
        )
        if item is None or not item.capabilities.open_reference:
            raise RpcError(INVALID_PARAMS, "resource is not an openable member of this question")
        classified = classify_resource_uri(reference)
        if item.kind == "local" and classified.normalized is not None:
            path = inventory.source(classified.normalized)
            inventory.relative_to_assets(classified.normalized)
            if action == "reveal_reference":
                dry_run = opened.services.assets.launcher.open_directory(path.parent, execute=False)
                result = opened.services.assets.launcher.open_directory(path.parent, execute=True)
            else:
                dry_run = opened.services.assets.launcher.open_file(path, execute=False)
                result = opened.services.assets.launcher.open_file(path, execute=True)
        elif item.kind == "external" and action == "open_reference":
            url = f"https:{reference}" if reference.startswith("//") else reference
            dry_run = opened.services.assets.launcher.open_url(url, execute=False)
            result = opened.services.assets.launcher.open_url(url, execute=True)
        else:
            raise RpcError(INVALID_PARAMS, "resource action is not supported for this resource kind")
        return {
            "dryRun": {"command": list(dry_run)},
            "result": {"command": list(result)},
            "revision": self._refresh_revision(opened),
        }

    def asset_create(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = _required_string(params, "questionId")
        asset_id = _required_string(params, "assetId")
        source = _required_string(params, "source", allow_empty=True)
        package = _asset_package(params, question_id, asset_id)
        dry_asset = opened.services.assets.ingest_package(
            package, opened.context.root, dry_run=True
        )
        candidate, _, _ = parse_question_text(source)
        previous = opened.snapshot.locate(question_id).question
        reference = f"qbank-asset:{asset_id}"
        if reference not in candidate.assets:
            candidate = candidate.model_copy(update={"assets": [*candidate.assets, reference]})
        patch = _question_patch(previous, candidate)
        committed = opened.services.assets.ingest_package(
            package, opened.context.root, dry_run=False
        )
        try:
            validation = self._validate_source(question_id, render_question(candidate))
            if not validation["ok"]:
                opened.services.assets.discard_new_asset(question_id, asset_id)
                return {
                    "ok": False,
                    "validation": validation,
                    "asset": dry_asset.model_dump(mode="json"),
                }
            dry_question = opened.services.studio.save_question(
                question_id,
                patch,
                dry_run=True,
                command="qbank studio protocol asset create",
            )
            if not dry_question.ok:
                opened.services.assets.discard_new_asset(question_id, asset_id)
                return {
                    "ok": False,
                    "asset": dry_asset.model_dump(mode="json"),
                    "question": dry_question.model_dump(mode="json"),
                }
            saved = opened.services.studio.save_question(
                question_id,
                patch,
                dry_run=False,
                command="qbank studio protocol asset create",
            )
        except Exception as original:
            try:
                opened.services.assets.discard_new_asset(question_id, asset_id)
            except Exception as rollback:
                original.add_note(f"asset compensation failed: {rollback}")
            raise
        return {
            "ok": saved.ok,
            "asset": committed.model_dump(mode="json"),
            "question": saved.model_dump(mode="json"),
            "reference": reference,
            "revision": self._refresh_snapshot(opened),
        }

    def asset_replace(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = _required_string(params, "questionId")
        asset_id = _required_string(params, "assetId")
        representation = _asset_representation(params, "replacement")
        dry_run = opened.services.assets.replace(
            question_id,
            asset_id,
            representation,
            opened.context.root,
            dry_run=True,
        )
        result = opened.services.assets.replace(
            question_id,
            asset_id,
            representation,
            opened.context.root,
            dry_run=False,
        )
        return {
            "dryRun": dry_run.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "revision": self._refresh_revision(opened),
        }

    def asset_render(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        question_id = _required_string(params, "questionId")
        asset_id = _required_string(params, "assetId")
        raw_formats_value: object = params.get("formats", ["svg", "png", "pdf"])
        if not isinstance(raw_formats_value, list):
            raise RpcError(INVALID_PARAMS, "formats must be an array of strings")
        format_items = cast(list[object], raw_formats_value)
        if not all(isinstance(item, str) for item in format_items):
            raise RpcError(INVALID_PARAMS, "formats must be an array of strings")
        raw_formats = cast(list[str], format_items)
        formats = [AssetFormat(item) for item in raw_formats]
        dry_run = opened.services.assets.render_asset(
            question_id, asset_id, formats=formats, dry_run=True
        )
        result = opened.services.assets.render_asset(
            question_id, asset_id, formats=formats, dry_run=False
        )
        revision = self._refresh_revision(opened)
        self._record_asset_edit_guard(opened, question_id, asset_id, revision)
        return {
            "dryRun": dry_run.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "assets": self.asset_list({"questionId": question_id}),
            "revision": revision,
        }

    def asset_reconcile(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        question_id = _required_string(params, "questionId")
        asset_id = _required_string(params, "assetId")
        self._require_reconcile_revision(params, opened, question_id, asset_id)
        before = opened.services.assets.show_asset(question_id, asset_id).asset
        dry_run = opened.services.assets.reconcile_editor_change(
            question_id, asset_id, dry_run=True
        )
        reconciled = opened.services.assets.reconcile_editor_change(
            question_id, asset_id, dry_run=False
        )
        after = opened.services.assets.show_asset(question_id, asset_id).asset
        changed = before != after
        render: dict[str, Any] | None = None
        if changed:
            render = self.asset_render(
                {
                    "questionId": question_id,
                    "assetId": asset_id,
                    "formats": ["svg", "png", "pdf"],
                    "expectedRevision": self._refresh_revision(opened),
                }
            )
        return {
            "changed": changed,
            "dryRun": dry_run.model_dump(mode="json"),
            "reconciled": reconciled.model_dump(mode="json"),
            "render": render,
            "revision": self._refresh_revision(opened),
        }

    def history_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        question_id = _required_string(params, "questionId")
        asset_events = opened.services.assets.history(question_id).events
        return [
            item.model_dump(mode="json", exclude_none=True)
            for item in opened.services.history.timeline(question_id, asset_events)
        ]

    def paper_list(self, _params: dict[str, Any]) -> list[dict[str, Any]]:
        opened = self._opened()
        return [
            self._paper_item(opened, path) for path in opened.services.studio_project.list_papers()
        ]

    def paper_get(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._synchronize_snapshot(opened)
        path = self._paper_path(opened, _required_string(params, "path"))
        return {
            "path": path.relative_to(opened.context.root).as_posix(),
            "paper": load_paper(path).model_dump(mode="json", exclude_none=True),
            "revision": opened.revision,
        }

    def paper_create(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = Path(_required_string(params, "path"))
        title = _required_string(params, "title")
        question_ids = _string_list(params, "questionIds", allow_empty=False)
        dry_run = opened.services.studio_project.create_paper(
            path, title, question_ids, dry_run=True
        )
        paper = opened.services.studio_project.create_paper(
            path, title, question_ids, dry_run=False
        )
        return {
            "ok": True,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "paper": paper.model_dump(mode="json", exclude_none=True),
            "revision": self._refresh_revision(opened),
        }

    def paper_save(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = self._paper_path(opened, _required_string(params, "path"))
        raw_paper = params.get("paper")
        if not isinstance(raw_paper, dict):
            raise RpcError(INVALID_PARAMS, "paper must be an object")
        paper = Paper.model_validate(raw_paper)
        service = cast(StudioProjectAdapter, opened.services.studio_project).papers
        dry_run = service.save(
            path, paper, dry_run=True, command="qbank studio protocol paper save"
        )
        saved = service.save(path, paper, dry_run=False, command="qbank studio protocol paper save")
        return {
            "ok": True,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "paper": saved.model_dump(mode="json", exclude_none=True),
            "revision": self._refresh_revision(opened),
        }

    def paper_add_questions(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = self._paper_path(opened, _required_string(params, "path"))
        question_ids = _string_list(params, "questionIds", allow_empty=False)
        dry_run = opened.services.studio_project.add_to_paper(path, question_ids, dry_run=True)
        paper = opened.services.studio_project.add_to_paper(path, question_ids, dry_run=False)
        return {
            "ok": True,
            "dryRun": dry_run.model_dump(mode="json", exclude_none=True),
            "paper": paper.model_dump(mode="json", exclude_none=True),
            "revision": self._refresh_revision(opened),
        }

    def paper_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        path = self._paper_path(opened, _required_string(params, "path"))
        report = opened.services.studio_project.validate_paper(path)
        return report.model_dump(mode="json", exclude_none=True)

    def paper_build(self, params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._require_current_revision(params, opened)
        path = self._paper_path(opened, _required_string(params, "path"))
        output = params.get("output")
        if output is not None and not isinstance(output, str):
            raise RpcError(INVALID_PARAMS, "output must be a string or null")
        options = params.get("options", {})
        if not isinstance(options, dict):
            raise RpcError(INVALID_PARAMS, "options must be an object")
        output_format = _optional_string(params, "format", default="html")
        if output_format not in {"md", "html", "docx"}:
            raise RpcError(INVALID_PARAMS, "format must be md, html, or docx")
        request = PaperBuildRequest(
            output_format=cast(Literal["md", "html", "docx"], output_format),
            output=Path(output).expanduser() if output else None,
            options=PaperBuildOptions.model_validate(options),
        )
        result = opened.services.studio_project.build_paper(path, request)
        return {
            "ok": result.ok,
            "result": result.model_dump(mode="json", exclude_none=True),
            "revision": opened.revision,
        }

    def application_shutdown(self, _params: dict[str, Any]) -> dict[str, Any]:
        self.shutdown_requested = True
        return {"ok": True}

    def _validate_source(self, question_id: str, source: str) -> dict[str, Any]:
        opened = self._opened()
        diagnostics: list[dict[str, Any]] = []
        try:
            candidate, duplicates, _ = parse_question_text(source)
        except (MarkdownParseError, ValidationError) as exc:
            return {
                "ok": False,
                "diagnostics": [
                    {
                        "severity": "error",
                        "code": "invalid_source_file",
                        "message": str(exc),
                    }
                ],
                "canonicalChanged": False,
            }
        if candidate.id != question_id:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "question_identity_mismatch",
                    "field": "id",
                    "message": f"source ID {candidate.id} does not match {question_id}",
                }
            )
        for duplicate in duplicates:
            diagnostics.append(
                {
                    "severity": "error",
                    "code": "duplicate_section",
                    "field": duplicate,
                    "message": f"duplicate canonical section: {duplicate}",
                }
            )
        canonical_changed = render_question(candidate) != source
        if canonical_changed:
            diagnostics.append(
                {
                    "severity": "warning",
                    "code": "canonical_source_difference",
                    "message": "qbank canonical serialization differs; save will return the authoritative source",
                }
            )
        if not any(item["severity"] == "error" for item in diagnostics):
            previous = opened.snapshot.locate(question_id).question
            dry_run = opened.services.studio.save_question(
                question_id,
                _question_patch(previous, candidate),
                dry_run=True,
                command="qbank studio protocol validate",
            )
            diagnostics.extend(
                item.model_dump(mode="json", exclude_none=True)
                for item in [*dry_run.validation_errors, *dry_run.validation_warnings]
            )
        return {
            "ok": not any(item.get("severity", "error") == "error" for item in diagnostics),
            "diagnostics": diagnostics,
            "canonicalChanged": canonical_changed,
        }

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

    @staticmethod
    def _paper_path(opened: OpenRepository, value: str) -> Path:
        return cast(StudioProjectAdapter, opened.services.studio_project).paper_path(Path(value))

    def _paper_item(self, opened: OpenRepository, path: Path) -> dict[str, Any]:
        paper = load_paper(path)
        return {
            "path": path.relative_to(opened.context.root).as_posix(),
            "title": paper.title,
            "questionIds": [item.id for section in paper.sections for item in section.questions],
            "totalScore": paper.calculated_total,
        }

    def _asset_item(self, opened: OpenRepository, item: DesktopAssetItem) -> dict[str, Any]:
        manifest = item.manifest
        preferred = manifest.preferred_render if manifest is not None else None
        has_ipe = manifest is not None and any(
            representation.format == AssetFormat.IPE and representation.editable
            for representation in manifest.representations
        )
        preview_data_url = self._preview_data_url(opened, item.preview_path)
        diagnostic = (
            item.diagnostic.model_dump(mode="json", exclude_none=True)
            if item.diagnostic is not None
            else None
        )
        return {
            "assetId": item.asset_id or stable_legacy_asset_id(item.reference),
            "kind": item.kind,
            "reference": item.reference,
            "displayName": item.display_name,
            "declared": item.declared,
            "exists": item.exists,
            "diagnostic": diagnostic,
            "role": manifest.role if manifest is not None else "figure",
            "status": manifest.status.value if manifest is not None else item.kind,
            "preferredRepresentation": preferred,
            "previewDataUrl": preview_data_url,
            "capabilities": {
                "canEditIpe": has_ipe,
                "canReplace": item.kind == "logical" and item.capabilities.replace,
                "canOpen": item.capabilities.open_original or item.capabilities.open_reference,
                "canRender": item.kind == "logical" and item.capabilities.render,
                "canReveal": (
                    item.kind == "logical" and item.capabilities.show_directory
                )
                or (item.kind == "local" and item.capabilities.open_reference),
            },
            "representations": [
                {
                    "representationId": representation.representation_id,
                    "format": representation.format.value,
                    "stale": representation.stale,
                    "editable": representation.editable,
                    "renderable": representation.renderable,
                }
                for representation in (manifest.representations if manifest is not None else [])
            ],
        }

    @staticmethod
    def _preview_data_url(opened: OpenRepository, raw_path: str | None) -> str | None:
        if raw_path is None:
            return None
        try:
            path = Path(raw_path).resolve(strict=True)
            path.relative_to(opened.context.paths.assets.resolve(strict=True))
        except (OSError, ValueError):
            return None
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            return None
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return f"data:{media_type};base64," + base64.b64encode(path.read_bytes()).decode("ascii")

    def _record_asset_edit_guard(
        self,
        opened: OpenRepository,
        question_id: str,
        asset_id: str,
        revision: str,
    ) -> None:
        manifest = opened.services.assets.show_asset(question_id, asset_id).asset
        editor = next(
            (
                item
                for item in manifest.representations
                if item.format == AssetFormat.IPE and item.editable
            ),
            None,
        )
        if editor is None:
            return
        source = opened.services.assets.repository.representation_path(
            manifest,
            editor.representation_id,
        )
        if source is None or not source.is_file():
            return
        resolved = source.resolve(strict=True)
        self._asset_edit_guards[(question_id, asset_id)] = AssetEditGuard(
            revision=revision,
            source=resolved,
            source_hash=hashlib.sha256(resolved.read_bytes()).hexdigest(),
            other_files=_authoritative_file_snapshot(opened.context, exclude=resolved),
        )

    def _require_reconcile_revision(
        self,
        params: dict[str, Any],
        opened: OpenRepository,
        question_id: str,
        asset_id: str,
    ) -> str:
        expected = _required_string(params, "expectedRevision")
        current = repository_revision(opened.context)
        if current == expected:
            opened.revision = current
            return current
        guard = self._asset_edit_guards.get((question_id, asset_id))
        if (
            guard is not None
            and guard.revision == expected
            and guard.source.is_file()
            and hashlib.sha256(guard.source.read_bytes()).hexdigest() != guard.source_hash
            and _authoritative_file_snapshot(opened.context, exclude=guard.source)
            == guard.other_files
        ):
            opened.revision = current
            return current
        raise RpcError(
            CONFLICT,
            "repository changed outside the expected Ipe source edit",
            {"expectedRevision": expected, "actualRevision": current},
        )

    def _opened(self) -> OpenRepository:
        if self.repository is None:
            raise RpcError(REPOSITORY_NOT_OPEN, "open a qbank repository first")
        return self.repository

    @staticmethod
    def _ensure_projection_current(opened: OpenRepository) -> None:
        opened.services.questions.index.ensure_revision(opened.projection_revision)

    @staticmethod
    def _refresh_revision(opened: OpenRepository) -> str:
        opened.revision = repository_revision(opened.context)
        return opened.revision

    @classmethod
    def _refresh_snapshot(cls, opened: OpenRepository) -> str:
        opened.snapshot = opened.services.repository.scan()
        opened.projection_revision = question_projection_revision(opened.context)
        return cls._refresh_revision(opened)

    @classmethod
    def _synchronize_snapshot(cls, opened: OpenRepository) -> None:
        current = repository_revision(opened.context)
        if current == opened.revision:
            return
        opened.snapshot = opened.services.repository.scan()
        opened.projection_revision = question_projection_revision(opened.context)
        opened.revision = current

    @staticmethod
    def _require_current_revision(params: dict[str, Any], opened: OpenRepository) -> str:
        expected = _required_string(params, "expectedRevision")
        current = repository_revision(opened.context)
        if current != expected:
            raise RpcError(
                CONFLICT,
                "repository changed after this document was loaded",
                {"expectedRevision": expected, "actualRevision": current},
            )
        opened.revision = current
        return current


def _summary_hit(hit: SearchHit) -> dict[str, Any]:
    """Normalize an index projection to the stable Studio question summary."""

    return {
        "id": hit.id,
        "title": hit.title,
        "subject": hit.subject or "",
        "chapter": hit.chapter or None,
        "topics": hit.topics.split(),
        "type": hit.question_type or "other",
        "status": hit.status or "draft",
        "difficulty": hit.difficulty or 1,
        "language": hit.language or "",
        "createdAt": hit.created_at,
    }


def _question_patch(previous: Question, candidate: Question) -> QuestionPatch:
    values = candidate.model_dump(mode="json")
    set_values = {
        field: values[field]
        for field in QUESTION_PATCHABLE_FIELDS
        if getattr(previous, field) != getattr(candidate, field)
    }
    previous_topics = set(previous.topics)
    candidate_topics = set(candidate.topics)
    return QuestionPatch(
        set=set_values,
        add_topics=[item for item in candidate.topics if item not in previous_topics],
        remove_topics=[item for item in previous.topics if item not in candidate_topics],
    )


def _asset_package(params: dict[str, Any], question_id: str, asset_id: str) -> AssetPackage:
    representation = _asset_representation(params, "original")
    return AssetPackage(
        schema_version="1.0",
        question_id=question_id,
        asset_id=asset_id,
        role=_optional_string(params, "role", default="figure"),
        status=AssetStatus.RAW,
        suggested_render=(
            None if representation.format == AssetFormat.IPE else representation.representation_id
        ),
        representations=[representation],
        provenance={"type": "studio-user-import"},
    )


def _asset_representation(params: dict[str, Any], purpose: str) -> AssetPackageRepresentation:
    media_type = _required_string(params, "mediaType")
    format_ = _MEDIA_FORMATS.get(media_type)
    if format_ is None:
        raise RpcError(INVALID_PARAMS, f"unsupported asset media type: {media_type}")
    encoded = _required_string(params, "dataBase64")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RpcError(INVALID_PARAMS, "dataBase64 is not valid Base64") from exc
    if len(raw) > 32 * 1024 * 1024:
        raise RpcError(INVALID_PARAMS, "asset input exceeds the 32 MiB Studio limit")
    digest = hashlib.sha256(raw).hexdigest()
    identifier = f"{purpose}-{digest[:8]}"
    return AssetPackageRepresentation(
        representation_id=identifier,
        format=format_,
        base64=encoded,
        purpose=purpose,
        editable=format_ == AssetFormat.IPE,
        content_hash=digest,
    )


def _required_string(params: dict[str, Any], name: str, *, allow_empty: bool = False) -> str:
    value = params.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise RpcError(INVALID_PARAMS, f"{name} must be a string")
    return value


def _optional_string(params: dict[str, Any], name: str, *, default: str) -> str:
    value = params.get(name, default)
    if not isinstance(value, str):
        raise RpcError(INVALID_PARAMS, f"{name} must be a string")
    return value


def _optional_int(params: dict[str, Any], name: str, default: int) -> int:
    value = params.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise RpcError(INVALID_PARAMS, f"{name} must be an integer")
    return value


def _string_list(params: dict[str, Any], name: str, *, allow_empty: bool = True) -> list[str]:
    value: object = params.get(name)
    if not isinstance(value, list):
        suffix = "" if allow_empty else " and must not be empty"
        raise RpcError(INVALID_PARAMS, f"{name} must be an array of strings{suffix}")
    raw_items = cast(list[object], value)
    if not all(isinstance(item, str) and item.strip() for item in raw_items) or (
        not allow_empty and not raw_items
    ):
        suffix = "" if allow_empty else " and must not be empty"
        raise RpcError(INVALID_PARAMS, f"{name} must be an array of strings{suffix}")
    items = cast(list[str], raw_items)
    return list(dict.fromkeys(item.strip() for item in items))


def _optional_string_list(params: dict[str, Any], name: str) -> list[str]:
    value = params.get(name, [])
    if value == []:
        return []
    return _string_list(params, name)


def _object_value(params: dict[str, Any], name: str) -> dict[str, Any]:
    value: object = params.get(name)
    if not isinstance(value, dict):
        raise RpcError(INVALID_PARAMS, f"{name} must be an object")
    return cast(dict[str, Any], value)


def _query_filters(params: dict[str, Any]) -> QueryFilters:
    values: dict[str, Any] = {
        "offset": _optional_int(params, "offset", 0),
        "limit": _optional_int(params, "limit", 500),
    }
    aliases = {
        "subject": "subject",
        "chapter": "chapter",
        "topics": "topics",
        "excludedTopics": "excluded_topics",
        "topicMode": "topic_mode",
        "type": "question_type",
        "status": "status",
        "difficultyMin": "difficulty_min",
        "difficultyMax": "difficulty_max",
        "language": "language",
        "year": "year",
        "text": "text",
    }
    for source, target in aliases.items():
        if source in params and params[source] is not None:
            values[target] = params[source]
    return QueryFilters.model_validate(values)


def _authoritative_file_snapshot(
    context: ProjectContext,
    *,
    exclude: Path,
) -> tuple[tuple[str, str], ...]:
    root = context.root.resolve(strict=True)
    excluded = exclude.resolve(strict=True)
    candidates = [
        context.root / "qbank.yaml",
        context.root / "taxonomy.yaml",
        context.root / "views.yaml",
    ]
    for directory in (
        context.paths.questions,
        context.paths.assets,
        context.paths.papers,
    ):
        if directory.exists():
            candidates.extend(item for item in directory.rglob("*") if item.is_file())
    snapshot: list[tuple[str, str]] = []
    for candidate in candidates:
        if not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise DataValidationError(
                f"authoritative path escapes the repository: {candidate}"
            ) from exc
        if is_reparse_point(candidate):
            raise DataValidationError(
                f"reparse points are not supported in authoritative data: {candidate}"
            )
        if resolved == excluded:
            continue
        snapshot.append((relative, hashlib.sha256(resolved.read_bytes()).hexdigest()))
    return tuple(sorted(set(snapshot)))


def _load_studio_math(
    context: ProjectContext,
) -> tuple[dict[str, str | list[str | int]], list[str]]:
    path = context.paths.state / "studio-math.json"
    if not path.exists():
        return {}, []
    if is_reparse_point(path) or not path.is_file():
        return {}, ["Studio math configuration must be a regular non-link file"]
    try:
        path.resolve(strict=True).relative_to(context.root.resolve(strict=True))
        if path.stat().st_size > 64 * 1024:
            raise ValueError("configuration exceeds 64 KiB")
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
        payload_object = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
        values: object = payload_object.get("macros")
        if not isinstance(values, dict):
            raise ValueError("macros must be an object")
        macro_values = cast(dict[object, object], values)
        macros: dict[str, str | list[str | int]] = {}
        for name, value in macro_values.items():
            if not isinstance(name, str) or _MACRO_NAME.fullmatch(name) is None:
                raise ValueError(f"invalid macro name: {name}")
            if isinstance(value, str) and len(value) <= 1024:
                macros[name] = value
                continue
            if isinstance(value, list):
                parts = cast(list[object], value)
                if (
                    len(parts) == 2
                    and isinstance(parts[0], str)
                    and len(parts[0]) <= 1024
                    and isinstance(parts[1], int)
                    and not isinstance(parts[1], bool)
                    and 0 <= parts[1] <= 9
                ):
                    macros[name] = [parts[0], parts[1]]
                    continue
            raise ValueError(f"invalid macro value: {name}")
        cycle = _macro_cycle(macros)
        if cycle is not None:
            raise ValueError(f"recursive or excessively deep macro chain: {' -> '.join(cycle)}")
        return macros, []
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return {}, [f"Studio math configuration ignored: {exc}"]


def _macro_cycle(
    macros: dict[str, str | list[str | int]],
) -> list[str] | None:
    graph = {
        name: [
            reference
            for reference in _MACRO_REFERENCE.findall(
                value if isinstance(value, str) else str(value[0])
            )
            if reference in macros
        ]
        for name, value in macros.items()
    }
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> list[str] | None:
        if name in visiting:
            index = visiting.index(name)
            return [*visiting[index:], name]
        if name in visited:
            return None
        if len(visiting) >= 32:
            return [*visiting, name]
        visiting.append(name)
        for dependency in graph[name]:
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        visiting.pop()
        visited.add(name)
        return None

    for name in graph:
        cycle = visit(name)
        if cycle is not None:
            return cycle
    return None
