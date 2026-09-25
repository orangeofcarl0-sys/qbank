"""Studio Protocol adapter over shared qbank application services."""

from __future__ import annotations

import platform
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from qbank import __version__ as qbank_version
from qbank.application.revision import (
    question_projection_revision,
    repository_revision,
)
from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.diagnostics import DiagnosticServices, project_status_in_context
from qbank.errors import (
    ConflictError,
    DataValidationError,
    MarkdownParseError,
    QBankError,
    RepositoryLockedError,
)
from qbank.markdown_codec import parse_question_text, render_question
from qbank.models import (
    QueryFilters,
)
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
from qbank.studio_sidecar.methods_assets import AssetMethods
from qbank.studio_sidecar.methods_papers import PaperMethods
from qbank.studio_sidecar.methods_questions import QuestionMethods
from qbank.studio_sidecar.methods_taxonomy import TaxonomyMethods
from qbank.studio_sidecar.methods_views import ViewMethods
from qbank.studio_sidecar.session import (
    AssetEditGuard,
    OpenRepository,
    SnapshotQuestionRepository,
    optional_string,
    question_patch,
    required_string,
    summary_hit,
)
from qbank.studio_sidecar.studio_math import load_studio_math


class StudioApplication(
    QuestionMethods,
    TaxonomyMethods,
    ViewMethods,
    AssetMethods,
    PaperMethods,
):
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
        studio_version = optional_string(params, "studioVersion", default="0.3.0-beta.2")
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
        candidate = self._repository_candidate(required_string(params, "root"))
        result = self._repository_open_result(candidate)
        self.repository = candidate
        self._asset_edit_guards.clear()
        return result

    def repository_rebuild_index(self, params: dict[str, Any]) -> dict[str, Any]:
        candidate = self._repository_candidate(required_string(params, "root"))
        indexed = candidate.services.questions.rebuild_index()
        self._refresh_snapshot(candidate)
        result = self._repository_open_result(candidate)
        self.repository = candidate
        self._asset_edit_guards.clear()
        return {**result, "indexed": indexed}

    def repository_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        opened = self._opened()
        self._synchronize_snapshot(opened)
        return self._repository_status(opened)

    def application_shutdown(self, _params: dict[str, Any]) -> dict[str, Any]:
        self.shutdown_requested = True
        return {"ok": True}

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
                summary_hit(item)
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

    def _repository_status(self, opened: OpenRepository) -> dict[str, Any]:
        diagnostics = DiagnosticServices(
            repository=SnapshotQuestionRepository(opened.snapshot),
            validator=opened.services.diagnostics.validator,
            index=opened.services.diagnostics.index,
        )
        status = project_status_in_context(opened.context, diagnostics)
        macros, studio_warnings = load_studio_math(opened.context)
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
        expected = required_string(params, "expectedRevision")
        current = repository_revision(opened.context)
        if current != expected:
            raise RpcError(
                CONFLICT,
                "repository changed after this document was loaded",
                {"expectedRevision": expected, "actualRevision": current},
            )
        opened.revision = current
        return current

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
                question_patch(previous, candidate),
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
