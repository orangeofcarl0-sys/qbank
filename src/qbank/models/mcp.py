"""Typed contracts used by the optional local MCP adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from qbank.models.asset import AssetPackage, AssetStatus
from qbank.models.common import ResultModel, StrictModel
from qbank.models.paper import Paper
from qbank.models.question import Question, QuestionPatch
from qbank.models.results import CodexCliCandidate, Diagnostic, SearchHit


def _diagnostics() -> list[Diagnostic]:
    return []


def _codex_cli_candidates() -> list[CodexCliCandidate]:
    return []


class McpAffectedObject(ResultModel):
    """One authoritative object named by a prepared mutation."""

    kind: Literal["question", "tag", "paper", "asset"]
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
    operation: Literal[
        "ingest",
        "patch",
        "tag_change",
        "paper",
        "asset_ingest",
        "asset_status",
        "asset_preferred",
    ]
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
    status: Literal["prepared", "committing", "committed", "cancelled", "expired"]
    repository_revision: str
    result: JsonValue | None = None
    idempotent_replay: bool = False
    operation: str | None = None
    expires_at: datetime | None = None
    code: str | None = None


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


class AssetIngestPrepareRequest(StrictModel):
    """One contained asset package import retained for a later commit."""

    package: AssetPackage
    package_root: str = "."
    download: bool = False


class AssetStatusPrepareRequest(StrictModel):
    """One logical asset lifecycle transition."""

    question_id: str
    asset_id: str
    status: AssetStatus


class AssetPreferredPrepareRequest(StrictModel):
    """Select an existing editor or render representation without launching it."""

    question_id: str
    asset_id: str
    kind: Literal["editor", "render"]
    representation_id: str


class McpQuestionSearchResult(ResultModel):
    """Search or structured-query results with an explicit mode."""

    ok: bool = True
    mode: Literal["search", "query"]
    items: list[SearchHit]


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
    codex_cli_candidates: list[CodexCliCandidate] = Field(default_factory=_codex_cli_candidates)


class McpConfigChange(ResultModel):
    """Dry-run or committed project MCP configuration change."""

    ok: bool
    action: Literal["install", "uninstall", "unchanged"]
    dry_run: bool
    configuration: str
    repository: str
    changed: bool
    backup: str | None = None
