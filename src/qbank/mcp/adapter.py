"""Repository-bound MCP adapter that calls qbank application services directly."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import cast

from pydantic import JsonValue

from qbank.application.revision import repository_revision
from qbank.composition import CoreProjectServices, create_core_project_services
from qbank.context import ProjectContext
from qbank.diagnostics import project_status_in_context
from qbank.errors import ConflictError, DataValidationError, QuestionNotFoundError
from qbank.mcp.operations import OperationStore, PreparedOperation
from qbank.models import (
    AssetShowResult,
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
    PaperPrepareRequest,
    PatchPrepareRequest,
    QueryFilters,
    Question,
    SearchHit,
    TagChangePrepareRequest,
    TagMutationResult,
    Taxonomy,
    ValidationReport,
)
from qbank.operations import ingest_questions_in_context
from qbank.papers import load_paper, validate_paper_in_context
from qbank.schemas import SchemaKind, schema_for
from qbank.transaction import MutationTransaction
from qbank.yaml_io import dump_yaml


class QbankMcpAdapter:
    """Expose one explicit qbank root without depending on CLI presentation code."""

    def __init__(
        self,
        context: ProjectContext,
        services: CoreProjectServices | None = None,
    ) -> None:
        self.context = context
        self.services = services or create_core_project_services(context)
        self.operations = OperationStore(self.revision, self._commit)

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
            search_items: list[Question | SearchHit] = []
            search_items.extend(self.services.questions.search_questions(text, limit=limit))
            return McpQuestionSearchResult(
                mode="search",
                items=search_items,
            )
        active = (filters or QueryFilters()).model_copy(update={"limit": limit})
        query_items: list[Question | SearchHit] = []
        query_items.extend(self.services.questions.query_questions(active))
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
        path = self._find_paper(paper_id)
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
        report = validate_paper_in_context(
            self.context,
            request.paper,
            assets=self.services.assets,
        )
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

    def operation_commit(
        self,
        operation_id: str,
        repository_revision: str,
    ) -> McpOperationResult:
        return self.operations.commit(operation_id, repository_revision)

    def operation_cancel(self, operation_id: str) -> McpOperationResult:
        return self.operations.cancel(operation_id)

    def _commit(self, operation: PreparedOperation) -> JsonValue:
        payload = operation.payload
        if isinstance(payload, IngestPrepareRequest):
            ingest_result = ingest_questions_in_context(
                self.context,
                payload.questions,
                services=self.services.mutations,
                options=IngestOptions(
                    upsert=payload.upsert,
                    command="qbank mcp operation_commit",
                ),
            )
            return cast(JsonValue, ingest_result.model_dump(mode="json", exclude_none=True))
        if isinstance(payload, PatchPrepareRequest):
            patch_result = self.services.questions.patch_question(
                payload.question_id,
                payload.patch,
                dry_run=False,
                command="qbank mcp operation_commit",
            )
            return cast(JsonValue, patch_result.model_dump(mode="json", exclude_none=True))
        if isinstance(payload, TagChangePrepareRequest):
            tag_result = self._tag_change(payload, dry_run=False)
            return cast(JsonValue, tag_result.model_dump(mode="json", exclude_none=True))
        path = self._paper_path(payload.path)
        transaction = MutationTransaction()
        transaction.write(
            path,
            dump_yaml(payload.paper.model_dump(mode="json", exclude_none=True)) + "\n",
        )
        transaction.commit()
        return cast(JsonValue, self.paper_get(path.stem).model_dump(mode="json"))

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
        if self.revision() != revision:
            raise ConflictError("repository changed while the operation was being prepared")
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
        ),
        preview: McpPrepareResult,
    ) -> McpPrepareResult:
        return self.operations.add(request, preview)

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

    def _find_paper(self, paper_id: str) -> Path:
        if any(character in paper_id for character in ("/", "\\")):
            path = self._paper_path(paper_id)
            if path.is_file():
                return path
            raise QuestionNotFoundError(f"paper not found: {paper_id}")
        matches = [
            path
            for pattern in ("*.yaml", "*.yml")
            for path in self.context.paths.papers.rglob(pattern)
            if path.stem == paper_id
        ]
        if not matches:
            raise QuestionNotFoundError(f"paper not found: {paper_id}")
        if len(matches) > 1:
            raise DataValidationError(f"ambiguous paper id: {paper_id}")
        return matches[0]
