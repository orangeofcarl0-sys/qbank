"""Domain errors and stable process exit codes."""

from enum import IntEnum

from pydantic import ValidationError

from qbank.models.results import DiagnosticCode


class ExitCode(IntEnum):
    """Stable command-line exit codes."""

    SUCCESS = 0
    GENERAL = 1
    CLI_USAGE = 2
    VALIDATION = 3
    NOT_FOUND = 4
    CONFLICT = 5
    EXPORT = 6
    DEPENDENCY = 7


class QBankError(Exception):
    """Base exception carrying a process exit code."""

    exit_code = ExitCode.GENERAL
    code = DiagnosticCode.GENERAL_ERROR


class ProjectNotFoundError(QBankError):
    """Raised when no qbank project can be found."""

    code = DiagnosticCode.PROJECT_NOT_FOUND


class QuestionNotFoundError(QBankError):
    """Raised when a question ID does not exist."""

    exit_code = ExitCode.NOT_FOUND
    code = DiagnosticCode.QUESTION_NOT_FOUND


class ConflictError(QBankError):
    """Raised for duplicate IDs and write conflicts."""

    exit_code = ExitCode.CONFLICT
    code = DiagnosticCode.CONFLICT


class DataValidationError(QBankError):
    """Raised for invalid question, patch, or paper input."""

    exit_code = ExitCode.VALIDATION
    code = DiagnosticCode.DATA_VALIDATION


class MarkdownParseError(DataValidationError):
    """Raised for malformed authoritative question Markdown."""

    code = DiagnosticCode.INVALID_SOURCE_FILE


class ExportError(QBankError):
    """Raised when an artifact cannot be exported."""

    exit_code = ExitCode.EXPORT
    code = DiagnosticCode.EXPORT_FAILED


class DependencyMissingError(QBankError):
    """Raised when an optional external tool is unavailable."""

    exit_code = ExitCode.DEPENDENCY
    code = DiagnosticCode.DEPENDENCY_MISSING


class AssetNotFoundError(QBankError):
    """Raised when a registered asset or representation does not exist."""

    exit_code = ExitCode.NOT_FOUND
    code = DiagnosticCode.ASSET_NOT_FOUND


class AssetConflictError(QBankError):
    """Raised when an asset import would overwrite different source content."""

    exit_code = ExitCode.CONFLICT
    code = DiagnosticCode.ASSET_CONFLICT


class AssetCommandError(QBankError):
    """Raised when a trusted local asset command fails."""

    exit_code = ExitCode.EXPORT
    code = DiagnosticCode.ASSET_COMMAND_FAILED


class IpeUnavailableError(QBankError):
    """Raised when the configured or discovered Ipe toolchain is unavailable."""

    exit_code = ExitCode.DEPENDENCY
    code = DiagnosticCode.IPE_UNAVAILABLE


def pydantic_error_text(exc: ValidationError) -> str:
    """Return stable validation text without Pydantic-version URLs."""
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
        for error in exc.errors(include_url=False)
    )
