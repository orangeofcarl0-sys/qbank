"""Typed contracts used by the optional local MCP adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from qbank.models.common import ResultModel, StrictModel
from qbank.models.paper import Paper
from qbank.models.question import Question, QuestionPatch
from qbank.models.results import Diagnostic, SearchHit


def _diagnostics() -> list[Diagnostic]:
    return []


class McpAffectedObject(ResultModel):
    """One authoritative object named by a prepared mutation."""

    kind: Literal["question", "tag", "paper"]
    id: str
    action: str
    path: str | None = None


class McpFieldDiff(ResultModel):
    """One JSON-serializable before/after field change."""

    object_id: str
    field: str
    before: JsonValue | None = None
    after: JsonValue | None = None


class McpValidation(ResultModel):
    """Normalized validation outcome for every prepare operation."""

    ok: bool
    diagnostics: list[Diagnostic] = Field(default_factory=_diagnostics)


class McpPrepareResult(ResultModel):
    """A read-only mutation preview retained for a later commit."""

    ok: bool
    operation_id: str
    operation: Literal["ingest", "patch", "tag_change", "paper"]
    affected_objects: list[McpAffectedObject]
    diff: list[McpFieldDiff]
    validation: McpValidation
    repository_revision: str
    committable: bool
    expires_at: datetime


class McpOperationResult(ResultModel):
    """Stable response for commit and cancel operations."""

    ok: bool
    operation_id: str
    status: Literal["committed", "cancelled"]
    repository_revision: str
    result: JsonValue | None = None
    idempotent_replay: bool = False


class IngestPrepareRequest(StrictModel):
    """Typed batch ingest request for MCP prepare."""

    questions: list[Question] = Field(min_length=1)
    upsert: bool = False


class PatchPrepareRequest(StrictModel):
    """Typed structured patch request for MCP prepare."""

    question_id: str
    patch: QuestionPatch


class TagChangePrepareRequest(StrictModel):
    """Supported taxonomy mutation selected for MCP prepare."""

    action: Literal["rename", "merge", "delete", "normalize"]
    source: str | None = None
    target: str | None = None

    @model_validator(mode="after")
    def required_values_match_action(self) -> TagChangePrepareRequest:
        if self.action in {"rename", "merge"} and (not self.source or not self.target):
            raise ValueError(f"{self.action} requires source and target")
        if self.action == "delete" and not self.source:
            raise ValueError("delete requires source")
        return self


class PaperPrepareRequest(StrictModel):
    """A contained project-relative paper replacement or creation."""

    path: str
    paper: Paper

    @field_validator("path")
    @classmethod
    def path_is_nonempty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("paper path must not be empty")
        return normalized


class McpQuestionSearchResult(ResultModel):
    """Search or structured-query results with an explicit mode."""

    ok: bool = True
    mode: Literal["search", "query"]
    items: list[Question | SearchHit]


class McpPaperDocument(ResultModel):
    """One contained paper and its repository-relative identity."""

    ok: bool = True
    id: str
    path: str
    paper: Paper


class McpIntegrationStatus(ResultModel):
    """Project-local Codex MCP registration and runtime readiness."""

    ok: bool
    registered: bool
    configuration: str
    repository: str
    sdk_available: bool
    codex_cli_available: bool
    degraded: bool
    message: str


class McpConfigChange(ResultModel):
    """Dry-run or committed project MCP configuration change."""

    ok: bool
    action: Literal["install", "uninstall", "unchanged"]
    dry_run: bool
    configuration: str
    repository: str
    changed: bool
    backup: str | None = None
