"""FastMCP STDIO presentation for one repository-bound qbank adapter."""

# FastMCP consumes decorated local callables during registration.
# pyright: reportUnusedFunction=false

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ContentBlock, ToolAnnotations
from pydantic import BaseModel, JsonValue, ValidationError

from qbank.errors import QBankError, pydantic_error_text
from qbank.mcp.adapter import QbankMcpAdapter
from qbank.models import (
    AssetIngestPrepareRequest,
    AssetPreferredPrepareRequest,
    AssetShowResult,
    AssetStatusPrepareRequest,
    IngestPrepareRequest,
    McpOperationResult,
    McpPaperDocument,
    McpPrepareResult,
    McpQuestionSearchResult,
    PaperHistoryEntry,
    PaperPrepareRequest,
    PatchPrepareRequest,
    QueryFilters,
    Question,
    TagChangePrepareRequest,
    Taxonomy,
    ValidationReport,
)

SERVER_INSTRUCTIONS = """1. For broad discovery, call question_search before question_get.
2. Every write must call a *_prepare tool and then operation_commit.
3. Never commit after the repository revision changes; prepare again.
4. Never invent answers, provenance, or review status.

This server is bound to one local qbank repository. Markdown is authoritative and
SQLite is only a rebuildable search projection. Prepare calls never write files.
"""

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
PREPARE = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
COMMIT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)
CANCEL = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


class QbankFastMCP(FastMCP[None]):
    """Preserve typed tool schemas while normalizing stable qbank error codes."""

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            cause = exc.__cause__
            if isinstance(cause, ValidationError):
                raise ToolError(
                    f"schema_validation_failed: {pydantic_error_text(cause)}"
                ) from cause
            if isinstance(cause, QBankError):
                code = cause.code.value
                message = str(cause)
                normalized = message if message.startswith(f"{code}:") else f"{code}: {message}"
                raise ToolError(normalized) from cause
            raise


def create_mcp_server(adapter: QbankMcpAdapter) -> FastMCP[None]:
    """Create a protocol server without starting transport or touching stdout."""
    server: FastMCP[None] = QbankFastMCP(
        "qbank",
        instructions=SERVER_INSTRUCTIONS,
        log_level="ERROR",
    )

    _register_read_tools(server, adapter)
    _register_operation_read_tools(server, adapter)
    _register_write_tools(server, adapter)
    _register_resources(server, adapter)
    return server


def _register_read_tools(server: FastMCP[None], adapter: QbankMcpAdapter) -> None:
    @server.tool(annotations=READ_ONLY, structured_output=True)
    def repository_status() -> dict[str, JsonValue]:
        """Return authoritative counts, index health, and repository revision."""
        return adapter.repository_status()

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def schema_get(
        kind: Literal["question", "paper", "patch", "asset", "asset-package"] = "question",
    ) -> dict[str, JsonValue]:
        """Return one Pydantic-generated qbank exchange Schema."""
        return adapter.schema_get(kind)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def question_search(
        text: str | None = None,
        filters: QueryFilters | None = None,
        limit: int = 20,
    ) -> McpQuestionSearchResult:
        """Search the projection or query authoritative Markdown with typed filters."""
        return adapter.question_search(text=text, filters=filters, limit=limit)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def question_get(question_id: str) -> Question:
        """Return one authoritative question by exact ID."""
        return adapter.question_get(question_id)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def question_validate(question_id: str | None = None) -> ValidationReport:
        """Validate one question or the full authoritative repository."""
        return adapter.question_validate(question_id)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def taxonomy_get() -> Taxonomy:
        """Return the project taxonomy registry."""
        return adapter.taxonomy_get()

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def asset_get(question_id: str, asset_id: str) -> AssetShowResult:
        """Return one logical asset manifest without opening or downloading it."""
        return adapter.asset_get(question_id, asset_id)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def paper_get(paper_id: str) -> McpPaperDocument:
        """Return one contained paper definition by ID or project-relative path."""
        return adapter.paper_get(paper_id)


def _register_operation_read_tools(
    server: FastMCP[None],
    adapter: QbankMcpAdapter,
) -> None:
    @server.tool(annotations=READ_ONLY, structured_output=True)
    def operation_get(operation_id: str) -> McpOperationResult:
        """Return durable prepare/commit state, including after a server restart."""
        return adapter.operation_get(operation_id)

    @server.tool(annotations=READ_ONLY, structured_output=True)
    def paper_history_get(paper_id: str) -> list[PaperHistoryEntry]:
        """Return append-only paper-definition history events."""
        return adapter.paper_history_get(paper_id)


def _register_write_tools(server: FastMCP[None], adapter: QbankMcpAdapter) -> None:
    @server.tool(annotations=PREPARE, structured_output=True)
    def ingest_prepare(request: IngestPrepareRequest) -> McpPrepareResult:
        """Dry-run an atomic batch ingest and retain its exact reviewed intent."""
        return adapter.ingest_prepare(request)

    @server.tool(annotations=PREPARE, structured_output=True)
    def patch_prepare(request: PatchPrepareRequest) -> McpPrepareResult:
        """Dry-run a structured question patch."""
        return adapter.patch_prepare(request)

    @server.tool(annotations=PREPARE, structured_output=True)
    def tag_change_prepare(request: TagChangePrepareRequest) -> McpPrepareResult:
        """Dry-run a rename, merge, delete, or normalization of taxonomy tags."""
        return adapter.tag_change_prepare(request)

    @server.tool(annotations=PREPARE, structured_output=True)
    def paper_prepare(request: PaperPrepareRequest) -> McpPrepareResult:
        """Validate and preview a contained paper creation or replacement."""
        return adapter.paper_prepare(request)

    @server.tool(annotations=PREPARE, structured_output=True)
    def asset_ingest_prepare(request: AssetIngestPrepareRequest) -> McpPrepareResult:
        """Dry-run a contained logical asset package without launching local programs."""
        return adapter.asset_ingest_prepare(request)

    @server.tool(annotations=PREPARE, structured_output=True)
    def asset_status_prepare(request: AssetStatusPrepareRequest) -> McpPrepareResult:
        """Dry-run a logical asset lifecycle-state update."""
        return adapter.asset_status_prepare(request)

    @server.tool(annotations=PREPARE, structured_output=True)
    def asset_preferred_prepare(request: AssetPreferredPrepareRequest) -> McpPrepareResult:
        """Dry-run editor or render preference selection without launching it."""
        return adapter.asset_preferred_prepare(request)

    @server.tool(annotations=COMMIT, structured_output=True)
    def operation_commit(
        operation_id: str,
        repository_revision: str,
    ) -> McpOperationResult:
        """Commit one unexpired preview if its repository revision is unchanged."""
        return adapter.operation_commit(operation_id, repository_revision)

    @server.tool(annotations=CANCEL, structured_output=True)
    def operation_cancel(operation_id: str) -> McpOperationResult:
        """Cancel an uncommitted operation; repeat cancellation is harmless."""
        return adapter.operation_cancel(operation_id)


def _register_resources(server: FastMCP[None], adapter: QbankMcpAdapter) -> None:
    @server.resource("qbank://repository/info", mime_type="application/json")
    def repository_info_resource() -> str:
        return _json(adapter.repository_status())

    @server.resource("qbank://schema/question", mime_type="application/schema+json")
    def question_schema_resource() -> str:
        return _json(adapter.schema_get("question"))

    @server.resource("qbank://schema/asset", mime_type="application/schema+json")
    def asset_schema_resource() -> str:
        return _json(adapter.schema_get("asset"))

    @server.resource("qbank://schema/paper", mime_type="application/schema+json")
    def paper_schema_resource() -> str:
        return _json(adapter.schema_get("paper"))

    @server.resource("qbank://taxonomy", mime_type="application/json")
    def taxonomy_resource() -> str:
        return _json(adapter.taxonomy_get())

    @server.resource("qbank://question/{id}", mime_type="application/json")
    def question_resource(id: str) -> str:
        return _json(adapter.question_get(id))

    @server.resource("qbank://paper/{id}", mime_type="application/json")
    def paper_resource(id: str) -> str:
        return _json(adapter.paper_get(id))

    @server.resource("qbank://history/{id}", mime_type="application/json")
    def history_resource(id: str) -> str:
        return _json(adapter.history_get(id))


def run_stdio_server(repository: Path) -> None:
    """Run the optional SDK only after an explicit, contained root is loaded."""
    adapter = QbankMcpAdapter.from_repository(repository)
    create_mcp_server(adapter).run(transport="stdio")


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
