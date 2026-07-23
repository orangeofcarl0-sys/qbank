"""Repository-bound MCP adapter that calls qbank application services directly."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import cast

from pydantic import JsonValue

from qbank.application.revision import repository_revision
from qbank.composition import CoreProjectServices, create_core_project_services
from qbank.context import ProjectContext
from qbank.diagnostics import project_status_in_context
from qbank.errors import DataValidationError, QuestionNotFoundError
from qbank.mcp.operations import OperationStore, PreparedOperation
from qbank.models import (
    AssetIngestPrepareRequest,
    AssetPreferredPrepareRequest,
    AssetShowResult,
    AssetStatusPrepareRequest,
    Diagnostic,
    IngestOptions,
    IngestPrepareRequest,
    McpAffectedObject,
    McpFieldDiff,
    McpOperationResult,
    McpPaperDocument,
    McpPrepareResult,
    McpQuestionSearchResult,
    Paper,
    PaperHistoryEntry,
    PaperPrepareRequest,
    PatchPrepareRequest,
    QueryFilters,
    Question,
    TagChangePrepareRequest,
    TagMutationResult,
    Taxonomy,
    ValidationReport,
)
from qbank.operations import apply_patch_in_context, ingest_questions_in_context
from qbank.papers import load_paper
from qbank.schemas import SchemaKind, schema_for
from qbank.utils import reject_reparse_points


class QbankMcpAdapter:
    """Expose one explicit qbank root without depending on CLI presentation code."""

    def __init__(
        self,
        context: ProjectContext,
        services: CoreProjectServices | None = None,
    ) -> None:
        self.context = context
        self.services = services or create_core_project_services(context)
        self.operations = OperationStore(
            self.revision,
            self._commit,
            directory=context.paths.state / "mcp-operations",
            lock=self.services.lock,
        )

    @classmethod
    def from_repository(cls, repository: Path) -> QbankMcpAdapter:
        return cls(ProjectContext.from_root(repository))

    def revision(self) -> str:
        return repository_revision(self.context)

    def repository_status(self) -> dict[str, JsonValue]:
        result = project_status_in_context(self.context, self.services.diagnostics)
        payload = result.model_dump(mode="json")
        payload["repository_revision"] = self.revision()
        return cast(dict[str, JsonValue], payload)

    @staticmethod
    def schema_get(kind: SchemaKind) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], schema_for(kind))

    def question_search(
        self,
        *,
        text: str | None = None,
        filters: QueryFilters | None = None,
        limit: int = 20,
    ) -> McpQuestionSearchResult:
        if limit < 1 or limit > 500:
            raise DataValidationError("limit must be between 1 and 500")
        if text and filters is not None:
            raise DataValidationError("use text search or structured filters, not both")
        if text:
            search_items = self.services.questions.search_questions(text, limit=limit)
            return McpQuestionSearchResult(
                mode="search",
                items=search_items,
            )
        active = (filters or QueryFilters()).model_copy(update={"limit": limit})
        query_items = self.services.questions.query_summaries(active)
        return McpQuestionSearchResult(
            mode="query",
            items=query_items,
        )

    def question_get(self, question_id: str) -> Question:
        return self.services.questions.get_question(question_id)

    def question_validate(self, question_id: str | None = None) -> ValidationReport:
        return self.services.questions.validate_repository(question_id=question_id)

    def taxonomy_get(self) -> Taxonomy:
        return self.services.tags.registry()

    def asset_get(self, question_id: str, asset_id: str) -> AssetShowResult:
        return self.services.assets.show_asset(question_id, asset_id)

    def paper_get(self, paper_id: str) -> McpPaperDocument:
        path = self.services.papers.find(paper_id)
        return McpPaperDocument(
            id=path.stem,
            path=path.relative_to(self.context.root).as_posix(),
            paper=load_paper(path),
        )

    def history_get(self, question_id: str) -> list[dict[str, JsonValue]]:
        question_events = self.services.history.history.list(question_id)
        asset_events = self.services.assets.history(question_id).events
        events = self.services.history.timeline(question_id, asset_events)
        if not events and not question_events:
            self.services.questions.get_question(question_id)
        return [cast(dict[str, JsonValue], item.model_dump(mode="json")) for item in events]

    def paper_history_get(self, paper_id: str) -> list[PaperHistoryEntry]:
        return self.services.papers.history(paper_id)

    def ingest_prepare(self, request: IngestPrepareRequest) -> McpPrepareResult:
        revision = self.revision()
        result = ingest_questions_in_context(
            self.context,
            request.questions,
            services=self.services.mutations,
            options=IngestOptions(
                upsert=request.upsert,
                dry_run=True,
                command="qbank mcp ingest_prepare",
            ),
        )
        diagnostics = [item for row in result.results for item in [*row.errors, *row.warnings]]
        affected = [
            McpAffectedObject(kind="question", id=row.id or "<invalid>", action=row.action)
            for row in result.results
        ]
        diff = self._ingest_diff(request)
        preview = self._preview(
            "ingest",
            revision,
            affected,
            diff,
            diagnostics,
            result.ok,
        )
        return self._store(request, preview)

    def patch_prepare(self, request: PatchPrepareRequest) -> McpPrepareResult:
        revision = self.revision()
        result = self.services.questions.patch_question(
            request.question_id,
            request.patch,
            dry_run=True,
            command="qbank mcp patch_prepare",
        )
        diagnostics = [*result.validation_errors, *result.validation_warnings]
        diff = [
            McpFieldDiff(
                object_id=request.question_id,
                field=change.field,
                before=change.old,
                after=change.new,
            )
            for change in result.changes
        ]
        preview = self._preview(
            "patch",
            revision,
            [McpAffectedObject(kind="question", id=request.question_id, action="patch")],
            diff,
            diagnostics,
            result.ok,
        )
        return self._store(request, preview)

    def tag_change_prepare(self, request: TagChangePrepareRequest) -> McpPrepareResult:
        revision = self.revision()
        result = self._tag_change(request, dry_run=True)
        affected = [
            McpAffectedObject(kind="question", id=change.id, action=request.action)
            for change in result.changes
        ]
        affected.append(
            McpAffectedObject(
                kind="tag",
                id=request.source or "taxonomy",
                action=request.action,
                path="taxonomy.yaml",
            )
        )
        diff = [
            McpFieldDiff(
                object_id=change.id,
                field="topics",
                before=cast(JsonValue, change.before),
                after=cast(JsonValue, change.after),
            )
            for change in result.changes
        ]
        preview = self._preview(
            "tag_change",
            revision,
            affected,
            diff,
            result.warnings,
            result.ok,
        )
        return self._store(request, preview)

    def paper_prepare(self, request: PaperPrepareRequest) -> McpPrepareResult:
        revision = self.revision()
        path = self._paper_path(request.path)
        previous = load_paper(path) if path.is_file() else None
        report = self.services.papers.validate(request.paper)
        diff = self._paper_diff(path.stem, previous, request.paper)
        preview = self._preview(
            "paper",
            revision,
            [
                McpAffectedObject(
                    kind="paper",
                    id=path.stem,
                    action="update" if previous else "create",
                    path=path.relative_to(self.context.root).as_posix(),
                )
            ],
            diff,
            report.issues,
            report.ok,
        )
        return self._store(request, preview)

    def asset_ingest_prepare(self, request: AssetIngestPrepareRequest) -> McpPrepareResult:
        revision = self.revision()
        package_root = self._package_root(request.package_root)
        result = self.services.assets.ingest_package(
            request.package,
            package_root,
            dry_run=True,
            download=request.download,
        )
        preview = self._preview(
            "asset_ingest",
            revision,
            [
                McpAffectedObject(
                    kind="asset",
                    id=f"{request.package.question_id}/{request.package.asset_id}",
                    action=result.action,
                    path=result.manifest_path,
                )
            ],
            [],
            result.warnings,
            result.ok,
        )
        return self._store(request, preview)

    def asset_status_prepare(self, request: AssetStatusPrepareRequest) -> McpPrepareResult:
        revision = self.revision()
        current = self.services.assets.show_asset(request.question_id, request.asset_id).asset
        result = self.services.assets.set_status(
            request.question_id,
            request.asset_id,
            request.status,
            dry_run=True,
        )
        preview = self._preview(
            "asset_status",
            revision,
            [
                McpAffectedObject(
                    kind="asset",
                    id=f"{request.question_id}/{request.asset_id}",
                    action="set_status",
                    path=result.manifest_path,
                )
            ],
            [
                McpFieldDiff(
                    object_id=request.asset_id,
                    field="status",
                    before=current.status.value,
                    after=request.status.value,
                )
            ],
            result.warnings,
            result.ok,
        )
        return self._store(request, preview)

    def asset_preferred_prepare(
        self,
        request: AssetPreferredPrepareRequest,
    ) -> McpPrepareResult:
        revision = self.revision()
        current = self.services.assets.show_asset(request.question_id, request.asset_id).asset
        result = self.services.assets.set_preference(
            request.question_id,
            request.asset_id,
            request.representation_id,
            kind=request.kind,
            dry_run=True,
        )
        field = "preferred_editor" if request.kind == "editor" else "preferred_render"
        preview = self._preview(
            "asset_preferred",
            revision,
            [
                McpAffectedObject(
                    kind="asset",
                    id=f"{request.question_id}/{request.asset_id}",
                    action=f"set_{request.kind}",
                    path=result.manifest_path,
                )
            ],
            [
                McpFieldDiff(
                    object_id=request.asset_id,
                    field=field,
                    before=getattr(current, field),
                    after=request.representation_id,
                )
            ],
            result.warnings,
            result.ok,
        )
        return self._store(request, preview)

    def operation_commit(
        self,
        operation_id: str,
        repository_revision: str,
    ) -> McpOperationResult:
        return self.operations.commit(operation_id, repository_revision)

    def operation_get(self, operation_id: str) -> McpOperationResult:
        return self.operations.get(operation_id)

    def operation_cancel(self, operation_id: str) -> McpOperationResult:
        return self.operations.cancel(operation_id)

    def _commit(self, operation: PreparedOperation) -> JsonValue:
        payload = operation.payload
        verified_revision = operation.verified_revision
        if verified_revision is None:
            raise RuntimeError("MCP commit requires a verified repository revision")
        if isinstance(payload, IngestPrepareRequest):
            ingest_result = ingest_questions_in_context(
                self.context,
                payload.questions,
                services=self.services.mutations,
                options=IngestOptions(
                    upsert=payload.upsert,
                    command="qbank mcp operation_commit",
                ),
                _verified_revision=verified_revision,
            )
            return cast(JsonValue, ingest_result.model_dump(mode="json", exclude_none=True))
        if isinstance(payload, PatchPrepareRequest):
            patch_result = apply_patch_in_context(
                self.context,
                payload.question_id,
                payload.patch,
                services=self.services.mutations,
                dry_run=False,
                command="qbank mcp operation_commit",
                _verified_revision=verified_revision,
            )
            return cast(JsonValue, patch_result.model_dump(mode="json", exclude_none=True))
        if isinstance(payload, TagChangePrepareRequest):
            tag_result = self._tag_change(payload, dry_run=False)
            return cast(JsonValue, tag_result.model_dump(mode="json", exclude_none=True))
        if isinstance(
            payload,
            AssetIngestPrepareRequest | AssetStatusPrepareRequest | AssetPreferredPrepareRequest,
        ):
            return self._commit_asset(payload)
        self.services.papers.save(
            payload.path,
            payload.paper,
            dry_run=False,
            command="qbank mcp operation_commit",
            _verified_revision=verified_revision,
        )
        return cast(
            JsonValue, self.paper_get(self._paper_path(payload.path).stem).model_dump(mode="json")
        )

    def _commit_asset(
        self,
        payload: (
            AssetIngestPrepareRequest | AssetStatusPrepareRequest | AssetPreferredPrepareRequest
        ),
    ) -> JsonValue:
        if isinstance(payload, AssetIngestPrepareRequest):
            asset_result = self.services.assets.ingest_package(
                payload.package,
                self._package_root(payload.package_root),
                dry_run=False,
                download=payload.download,
            )
            return cast(JsonValue, asset_result.model_dump(mode="json", exclude_none=True))
        if isinstance(payload, AssetStatusPrepareRequest):
            status_result = self.services.assets.set_status(
                payload.question_id,
                payload.asset_id,
                payload.status,
                dry_run=False,
            )
            return cast(JsonValue, status_result.model_dump(mode="json", exclude_none=True))
        preferred_result = self.services.assets.set_preference(
            payload.question_id,
            payload.asset_id,
            payload.representation_id,
            kind=payload.kind,
            dry_run=False,
        )
        return cast(JsonValue, preferred_result.model_dump(mode="json", exclude_none=True))

    def _tag_change(
        self,
        request: TagChangePrepareRequest,
        *,
        dry_run: bool,
    ) -> TagMutationResult:
        command = "qbank mcp tag_change"
        if request.action == "rename":
            return self.services.tags.rename(
                request.source or "", request.target or "", dry_run=dry_run, command=command
            )
        if request.action == "merge":
            return self.services.tags.merge(
                request.source or "", request.target or "", dry_run=dry_run, command=command
            )
        if request.action == "delete":
            return self.services.tags.delete(request.source or "", dry_run=dry_run, command=command)
        return self.services.tags.normalize(dry_run=dry_run, command=command)

    def _preview(
        self,
        operation: str,
        revision: str,
        affected: list[McpAffectedObject],
        diff: list[McpFieldDiff],
        diagnostics: list[Diagnostic],
        committable: bool,
    ) -> McpPrepareResult:
        operation_id, expires_at = self.operations.identity()
        return McpPrepareResult.model_validate(
            {
                "ok": committable,
                "operation_id": operation_id,
                "operation": operation,
                "affected_objects": affected,
                "diff": diff,
                "validation": {"ok": committable, "diagnostics": diagnostics},
                "repository_revision": revision,
                "committable": committable,
                "expires_at": expires_at,
            }
        )

    def _store(
        self,
        request: (
            IngestPrepareRequest
            | PatchPrepareRequest
            | TagChangePrepareRequest
            | PaperPrepareRequest
            | AssetIngestPrepareRequest
            | AssetStatusPrepareRequest
            | AssetPreferredPrepareRequest
        ),
        preview: McpPrepareResult,
    ) -> McpPrepareResult:
        return self.operations.add(request, preview)

    def _package_root(self, value: str) -> Path:
        pure = PurePosixPath(value.replace("\\", "/"))
        if PureWindowsPath(value).is_absolute() or pure.is_absolute() or ".." in pure.parts:
            raise DataValidationError("asset package root must be a contained relative path")
        lexical = self.context.root.joinpath(*pure.parts)
        try:
            reject_reparse_points(lexical, boundary=self.context.root)
        except ValueError as exc:
            raise DataValidationError("asset package root contains a reparse point") from exc
        candidate = lexical.resolve()
        if not candidate.is_relative_to(self.context.root.resolve()):
            raise DataValidationError("asset package root escapes the repository")
        if not candidate.is_dir():
            raise DataValidationError(f"asset package root does not exist: {value}")
        return candidate

    def _ingest_diff(self, request: IngestPrepareRequest) -> list[McpFieldDiff]:
        snapshot = self.services.repository.scan()
        result: list[McpFieldDiff] = []
        for question in request.questions:
            try:
                before = snapshot.locate(question.id).question.model_dump(mode="json")
            except QuestionNotFoundError:
                before = None
            after = question.model_dump(mode="json")
            for field in sorted(after):
                old = None if before is None else before.get(field)
                if before is None or old != after[field]:
                    result.append(
                        McpFieldDiff(
                            object_id=question.id,
                            field=field,
                            before=old,
                            after=after[field],
                        )
                    )
        return result

    @staticmethod
    def _paper_diff(
        paper_id: str,
        previous: Paper | None,
        current: Paper,
    ) -> list[McpFieldDiff]:
        before = previous.model_dump(mode="json") if previous is not None else {}
        after = current.model_dump(mode="json")
        return [
            McpFieldDiff(
                object_id=paper_id,
                field=field,
                before=before.get(field),
                after=value,
            )
            for field, value in after.items()
            if before.get(field) != value
        ]

    def _paper_path(self, value: str) -> Path:
        pure = PurePosixPath(value.replace("\\", "/"))
        if PureWindowsPath(value).is_absolute() or pure.is_absolute() or ".." in pure.parts:
            raise DataValidationError("paper path must be a contained relative path")
        candidate = self.context.root.joinpath(*pure.parts)
        if not candidate.is_relative_to(self.context.paths.papers):
            candidate = self.context.paths.papers.joinpath(*pure.parts)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.context.paths.papers.resolve()):
            raise DataValidationError("paper path escapes the configured papers directory")
        if resolved.suffix.casefold() not in {".yaml", ".yml"}:
            raise DataValidationError("paper path must use .yaml or .yml")
        return resolved
