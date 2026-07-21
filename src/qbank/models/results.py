"""Typed application and diagnostic result contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from qbank.models.asset import AssetManifest
from qbank.models.common import ResultModel
from qbank.models.question import Question

Severity = Literal["error", "warning", "info"]


class DiagnosticCode(StrEnum):
    """Stable machine-readable codes emitted by validation and mutations."""

    ASSET_MISSING = "asset_missing"
    ASSET_COMMAND_FAILED = "asset_command_failed"
    ASSET_COMMAND_REJECTED = "asset_command_rejected"
    ASSET_CONFLICT = "asset_conflict"
    ASSET_DERIVATION_INVALID = "asset_derivation_invalid"
    ASSET_FAILED = "asset_failed"
    ASSET_HASH_MISMATCH = "asset_hash_mismatch"
    ASSET_MANIFEST_INVALID = "asset_manifest_invalid"
    ASSET_NEEDS_REDRAW = "asset_needs_redraw"
    ASSET_NOT_FOUND = "asset_not_found"
    ASSET_OUTSIDE_ASSETS = "asset_outside_assets"
    ASSET_PACKAGE_INVALID = "asset_package_invalid"
    ASSET_PATH_ESCAPE = "asset_path_escape"
    ASSET_REPRESENTATION_MISSING = "asset_representation_missing"
    ASSET_RENDER_STALE = "asset_render_stale"
    CLI_USAGE = "cli_usage"
    CONFLICT = "conflict"
    CONTENT_IN_YAML = "content_in_yaml"
    DEPRECATED_QUESTION = "deprecated_question"
    DEPENDENCY_MISSING = "dependency_missing"
    GENERAL_ERROR = "general_error"
    DUPLICATE_BATCH_ID = "duplicate_batch_id"
    DUPLICATE_ID = "duplicate_id"
    DUPLICATE_QUESTION = "duplicate_question"
    DUPLICATE_SECTION = "duplicate_section"
    EMPTY_STEM = "empty_stem"
    EXTERNAL_ASSET = "external_asset"
    FILENAME_ID_MISMATCH = "filename_id_mismatch"
    INDEX_DIRTY = "index_dirty"
    INDEX_DISABLED = "index_disabled"
    INDEX_STALE = "index_stale"
    INDEX_UNAVAILABLE = "index_unavailable"
    DATA_VALIDATION = "data_validation"
    EXPORT_FAILED = "export_failed"
    INVALID_FILTER = "invalid_filter"
    INVALID_JSON = "invalid_json"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_RESOURCE_URI = "invalid_resource_uri"
    INVALID_SOURCE_FILE = "invalid_source_file"
    INVALID_TIMESTAMP = "invalid_timestamp"
    IPE_UNAVAILABLE = "ipe_unavailable"
    LATEX_BRACE_UNBALANCED = "latex_brace_unbalanced"
    LATEX_DELIMITER_UNBALANCED = "latex_delimiter_unbalanced"
    LATEX_DOLLAR_UNBALANCED = "latex_dollar_unbalanced"
    MISSING_OPTIONS = "missing_options"
    MISSING_QUESTION = "missing_question"
    MISSING_REVIEWED_ANSWER = "missing_reviewed_answer"
    MODEL_VALIDATION = "model_validation"
    MULTIPLE_CHOICE_ANSWER_FORMAT = "multiple_choice_answer_format"
    QUESTION_NOT_FOUND = "question_not_found"
    PROJECT_NOT_FOUND = "project_not_found"
    SINGLE_CHOICE_ANSWER_MISMATCH = "single_choice_answer_mismatch"
    TOTAL_SCORE_MISMATCH = "total_score_mismatch"
    UNDECLARED_ASSET_REFERENCE = "undeclared_asset_reference"
    UNUSED_ASSET = "unused_asset"


ASSET_ERROR_CODES = frozenset(
    {
        DiagnosticCode.ASSET_MISSING,
        DiagnosticCode.ASSET_COMMAND_REJECTED,
        DiagnosticCode.ASSET_DERIVATION_INVALID,
        DiagnosticCode.ASSET_FAILED,
        DiagnosticCode.ASSET_HASH_MISMATCH,
        DiagnosticCode.ASSET_MANIFEST_INVALID,
        DiagnosticCode.ASSET_NOT_FOUND,
        DiagnosticCode.ASSET_OUTSIDE_ASSETS,
        DiagnosticCode.ASSET_PACKAGE_INVALID,
        DiagnosticCode.ASSET_PATH_ESCAPE,
        DiagnosticCode.ASSET_REPRESENTATION_MISSING,
        DiagnosticCode.INVALID_RESOURCE_URI,
        DiagnosticCode.UNDECLARED_ASSET_REFERENCE,
    }
)


class Diagnostic(ResultModel):
    """One normalized diagnostic across questions, papers, and operations."""

    severity: Severity = "error"
    code: DiagnosticCode
    message: str
    id: str | None = None
    file: str | None = None
    field: str | None = None
    section: int | None = None
    line: int | None = None


ValidationIssue = Diagnostic


def _diagnostic_list() -> list[Diagnostic]:
    return []


def _change_dict_list() -> list[dict[str, Any]]:
    return []


class ValidationSummary(ResultModel):
    """Validation counters."""

    questions: int
    errors: int
    warnings: int
    info: int = 0


class ValidationReport(ResultModel):
    """Machine-readable question validation result."""

    ok: bool
    summary: ValidationSummary
    issues: list[Diagnostic]


class FieldChange(ResultModel):
    """One stable field-level mutation difference."""

    field: str
    old: Any = None
    new: Any = None


class AddQuestionResult(ResultModel):
    """Result of adding or upserting one complete question."""

    ok: bool
    dry_run: bool
    id: str
    action: Literal["create", "update"]
    path: str
    validation_errors: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    validation_warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    index_updated: bool


class PatchQuestionResult(ResultModel):
    """Result of applying a structured question patch."""

    ok: bool
    id: str
    dry_run: bool
    changes: list[FieldChange]
    validation_errors: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    validation_warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    index_updated: bool


class DeleteQuestionResult(ResultModel):
    """Result of deleting an authoritative source."""

    ok: bool
    dry_run: bool
    id: str
    path: str
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    index_updated: bool


class IngestItemResult(ResultModel):
    """Result associated with one physical JSONL line."""

    line: int
    id: str | None
    ok: bool
    action: Literal["create", "update"]
    errors: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    skipped: bool


class IngestResult(ResultModel):
    """Typed all-or-nothing or continue-on-error import result."""

    ok: bool
    dry_run: bool
    written: int
    total: int
    results: list[IngestItemResult]
    validation_warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    index_updated: bool
    would_write: int | None = None


class PaperValidationSummary(ResultModel):
    """Paper selection and score counters."""

    sections: int
    questions: int
    total_score: float
    errors: int
    warnings: int


class PaperValidationReport(ResultModel):
    """Typed paper validation report."""

    ok: bool
    summary: PaperValidationSummary
    issues: list[Diagnostic]


class ArtifactResult(ResultModel):
    """Common fields returned by generated artifact operations."""

    ok: bool
    format: str
    output: str
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)


class PaperBuildResult(ArtifactResult):
    """Paper build output details."""

    questions: int
    total_score: float
    assets: list[str]


class ExportResult(ArtifactResult):
    """Question collection export details."""

    questions: int


class PreviewResult(ResultModel):
    """Static preview build details."""

    ok: bool
    output: str
    questions: int
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)


class AssetListResult(ResultModel):
    """Logical assets registered for one question."""

    ok: bool
    question_id: str
    assets: list[AssetManifest]


class AssetShowResult(ResultModel):
    """One complete logical asset and its representations."""

    ok: bool
    asset: AssetManifest
    manifest_path: str


class AssetMutationResult(ResultModel):
    """Dry-run plan or committed logical-asset mutation."""

    ok: bool
    dry_run: bool
    action: Literal[
        "create",
        "update",
        "unchanged",
        "replace",
        "set_render",
        "set_editor",
        "finalize",
        "normalize",
        "reconcile",
        "restore",
    ]
    question_id: str
    asset_id: str
    manifest_path: str
    representations: list[str]
    question_updated: bool = False
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)


class AssetCommandResult(ResultModel):
    """A safe local open/edit command plan or successful launch."""

    ok: bool
    dry_run: bool
    action: Literal["open", "edit", "open_directory"]
    question_id: str
    asset_id: str
    representation_id: str
    target: str
    command: list[str]
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)


class AssetRenderResult(ResultModel):
    """Rendered derivative details."""

    ok: bool
    dry_run: bool
    action: Literal["render"] = "render"
    question_id: str
    asset_id: str
    manifest_path: str
    representations: list[str]
    question_updated: bool = False
    generated: list[str]
    commands: list[list[str]]
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)


class AssetHistoryEntry(ResultModel):
    """One append-only logical-asset history event."""

    timestamp: str
    operation: str
    question_id: str
    asset_id: str
    representation_ids: list[str]
    changes: list[dict[str, Any]] = Field(default_factory=_change_dict_list)


class AssetHistoryResult(ResultModel):
    """History events for one logical asset or all assets of a question."""

    ok: bool
    question_id: str
    asset_id: str | None = None
    events: list[AssetHistoryEntry]


class DesktopQuestionSummary(ResultModel):
    """One lightweight navigation row for the desktop editor."""

    id: str
    title: str
    subject: str
    status: str
    question_type: str
    difficulty: int
    needs_redraw: bool


class AssetCapabilities(ResultModel):
    """Actions that the desktop may safely offer for one asset item."""

    edit: bool = False
    replace: bool = False
    render: bool = False
    set_render: bool = False
    open_original: bool = False
    show_directory: bool = False
    restore: bool = False
    convert: bool = False
    open_reference: bool = False


class DesktopAssetItem(ResultModel):
    """Containment-checked asset state prepared for the desktop Inspector."""

    kind: Literal["logical", "local", "external", "invalid"]
    reference: str
    display_name: str
    asset_id: str | None = None
    manifest: AssetManifest | None = None
    preview_path: str | None = None
    exists: bool = False
    declared: bool = True
    diagnostic: Diagnostic | None = None
    capabilities: AssetCapabilities = Field(default_factory=AssetCapabilities)


def _desktop_asset_items() -> list[DesktopAssetItem]:
    return []


class DesktopQuestionDocument(ResultModel):
    """One editable question and its current logical-asset state."""

    question: Question
    source: str
    assets: list[AssetManifest]
    history: list[AssetHistoryEntry]
    asset_items: list[DesktopAssetItem] = Field(default_factory=_desktop_asset_items)


class DesktopPreviewResult(ResultModel):
    """Rendered interactive preview fragment and lifecycle warnings."""

    html: str
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)


class AssetNormalizeResult(ResultModel):
    """Legacy string-reference normalization outcome."""

    ok: bool
    dry_run: bool
    question_id: str
    assets: list[str]
    changed: bool
    changes: list[FieldChange]
    warnings: list[Diagnostic] = Field(default_factory=_diagnostic_list)
    index_updated: bool


class AssetValidationSummary(ResultModel):
    """Asset manifest, representation, and lifecycle counters."""

    assets: int
    representations: int
    errors: int
    warnings: int


class AssetValidationReport(ResultModel):
    """Repository-wide logical-asset validation report."""

    ok: bool
    summary: AssetValidationSummary
    issues: list[Diagnostic]


class AssetServeResult(ResultModel):
    """Local-only asset-management server endpoint details."""

    ok: bool
    host: Literal["127.0.0.1"]
    port: int
    url: str
    questions: int
    assets: int


class StatusResult(ResultModel):
    """Read-only project status summary."""

    ok: bool
    root: str
    questions: int
    by_status: dict[str, int]
    by_subject: dict[str, int]
    by_type: dict[str, int]
    invalid: int
    validation_errors: int
    index_dirty: bool
    index_updated_at: str | None
    git_repository: bool


class DoctorCheck(ResultModel):
    """One environment or project health check."""

    name: str
    status: Literal["PASS", "WARN", "FAIL"]
    message: str


class DoctorSummary(ResultModel):
    """Doctor check counters."""

    pass_: int = Field(alias="pass", serialization_alias="pass")
    warn: int
    fail: int


class DoctorReport(ResultModel):
    """Typed doctor output."""

    ok: bool
    summary: DoctorSummary
    checks: list[DoctorCheck]


class SearchHit(ResultModel):
    """One full-text search result."""

    id: str
    title: str
    chapter: str
    topics: str
    snippet: str
    rank: float


class IndexHealth(ResultModel):
    """Read-only search projection health used by status and doctor."""

    state: Literal["disabled", "clean", "dirty", "missing", "corrupt", "stale"]
    updated_at: str | None
    documents: dict[str, tuple[str, ...]]
    message: str

    @property
    def dirty(self) -> bool:
        """Return whether search results cannot be trusted."""
        return self.state not in {"disabled", "clean"}


class CodexInstructionsResult(ResultModel):
    """Repository-scoped operating rules exposed to AI clients."""

    ok: bool
    project_root: str
    rules: list[str]
    command_sequences: dict[str, list[str]]
    paths: dict[str, str]


class SkillInstallResult(ResultModel):
    """Plan or outcome of installing the repository Skill for one user."""

    ok: bool
    dry_run: bool
    action: Literal["plan", "installed", "already_installed"]
    source: str
    destination: str
    files: int
