"""Project health and status summaries built from one repository snapshot."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from qbank.application.ports import (
    IndexHealthPort,
    QuestionRepositoryPort,
    RepositoryValidatorPort,
)
from qbank.context import ProjectContext
from qbank.domain import RepositorySnapshot
from qbank.infrastructure import RepositoryValidationAdapter
from qbank.models import (
    ASSET_ERROR_CODES,
    DoctorCheck,
    DoctorReport,
    IndexHealth,
    ProjectConfig,
    StatusResult,
    ValidationReport,
)
from qbank.papers import pandoc_command
from qbank.repository import MarkdownQuestionRepository
from qbank.schemas import all_schemas
from qbank.search_index import SQLiteSearchIndex

CheckStatus = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class DiagnosticServices:
    """Injected repository, validator, and index-health dependencies."""

    repository: QuestionRepositoryPort
    validator: RepositoryValidatorPort
    index: IndexHealthPort


def _default_services(context: ProjectContext) -> DiagnosticServices:
    """Compatibility wiring for direct Python callers."""
    return DiagnosticServices(
        repository=MarkdownQuestionRepository(context),
        validator=RepositoryValidationAdapter(context),
        index=SQLiteSearchIndex(context),
    )


def project_status_in_context(
    context: ProjectContext,
    services: DiagnosticServices | None = None,
) -> StatusResult:
    """Return source counts and index/Git state without writing generated state."""
    services = services or _default_services(context)
    snapshot = services.repository.scan()
    report = services.validator.validate(snapshot=snapshot)
    questions = [record.question for record in snapshot.records]
    invalid_files = {
        issue.file
        for issue in report.issues
        if issue.severity == "error" and issue.file is not None
    }
    health = services.index.health(snapshot)
    return StatusResult(
        ok=True,
        root=str(context.root),
        questions=len(snapshot.paths),
        by_status=dict(sorted(Counter(question.status.value for question in questions).items())),
        by_subject=dict(sorted(Counter(question.subject for question in questions).items())),
        by_type=dict(sorted(Counter(question.type.value for question in questions).items())),
        invalid=len(invalid_files),
        validation_errors=report.summary.errors,
        index_dirty=health.dirty,
        index_updated_at=health.updated_at,
        git_repository=_is_git_repository(context.root),
    )


def project_status(root: Path, config: ProjectConfig) -> StatusResult:
    """Compatibility adapter for context-based project status."""
    return project_status_in_context(ProjectContext.from_config(root, config))


def _is_git_repository(root: Path) -> bool:
    """Detect a normal repository or worktree without spawning an external process."""
    return any((candidate / ".git").exists() for candidate in (root, *root.parents))


def _check(
    name: str,
    status: CheckStatus,
    message: str,
) -> DoctorCheck:
    return DoctorCheck(name=name, status=status, message=message)


def _schema_checks(root: Path) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    for name, expected in all_schemas().items():
        candidate = root / "schemas" / name
        if not candidate.is_file():
            checks.append(_check(f"schema_{name}", "FAIL", f"missing: {candidate}"))
            continue
        try:
            actual = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            checks.append(_check(f"schema_{name}", "FAIL", f"invalid JSON: {exc}"))
            continue
        checks.append(
            _check(
                f"schema_{name}",
                "PASS" if actual == expected else "FAIL",
                str(candidate) if actual == expected else "schema drift detected",
            )
        )
    return checks


def doctor_in_context(
    context: ProjectContext,
    services: DiagnosticServices | None = None,
) -> DoctorReport:
    """Run environment, containment, schema, index, and source checks."""
    services = services or _default_services(context)
    snapshot = services.repository.scan()
    checks = _environment_checks(context)
    checks.extend(_schema_checks(context.root))
    health = services.index.health(snapshot)
    checks.extend(_index_checks(context, health))
    report = services.validator.validate(snapshot=snapshot)
    checks.extend(_source_checks(snapshot, report))
    failures = sum(item.status == "FAIL" for item in checks)
    warnings = sum(item.status == "WARN" for item in checks)
    return DoctorReport.model_validate(
        {
            "ok": failures == 0,
            "summary": {
                "pass": len(checks) - failures - warnings,
                "warn": warnings,
                "fail": failures,
            },
            "checks": checks,
        }
    )


def doctor(root: Path, config: ProjectConfig) -> DoctorReport:
    """Compatibility adapter for context-based project diagnostics."""
    return doctor_in_context(ProjectContext.from_config(root, config))


def _environment_checks(context: ProjectContext) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(_check("python", "PASS" if sys.version_info >= (3, 11) else "FAIL", version))
    checks.append(_check("project_root", "PASS", str(context.root)))
    config_path = context.root / "qbank.yaml"
    checks.append(
        _check(
            "qbank_yaml",
            "PASS" if config_path.is_file() else "FAIL",
            str(config_path),
        )
    )
    checks.append(_check("path_containment", "PASS", "all configured paths contained"))
    for name in ("questions", "assets"):
        path = context.path(name)
        checks.append(_check(name, "PASS" if path.is_dir() else "FAIL", str(path)))
    writable = context.paths.state.is_dir() and os.access(context.paths.state, os.W_OK)
    checks.append(
        _check(
            "state_writable",
            "PASS" if writable else "FAIL",
            str(context.paths.state),
        )
    )
    checks.append(_trigram_check())
    checks.append(_pandoc_check(context))
    for name in ("paper.md.j2", "paper.html.j2"):
        candidate = context.paths.templates / name
        checks.append(
            _check(
                f"template_{name}",
                "PASS" if candidate.is_file() else "FAIL",
                str(candidate),
            )
        )
    reference = context.paths.reference_docx
    checks.append(
        _check(
            "reference_docx",
            "PASS" if reference.is_file() else "WARN",
            str(reference) if reference.is_file() else "not present; Pandoc defaults will be used",
        )
    )
    return checks


def _trigram_check() -> DoctorCheck:
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.execute(
                "CREATE VIRTUAL TABLE test_fts USING fts5(content, tokenize='trigram')"
            )
    except sqlite3.DatabaseError as exc:
        return _check("sqlite_fts5_trigram", "FAIL", str(exc))
    return _check("sqlite_fts5_trigram", "PASS", "FTS5 trigram available")


def _pandoc_check(context: ProjectContext) -> DoctorCheck:
    command = pandoc_command(context.config)
    pandoc = shutil.which(command[0]) if command else None
    return _check(
        "pandoc",
        "PASS" if pandoc else "WARN",
        pandoc or f"not found: {context.config.export.pandoc_command}",
    )


def _index_checks(
    context: ProjectContext,
    health: IndexHealth,
) -> list[DoctorCheck]:
    if health.state == "disabled":
        index_check = _check("index", "WARN", "index disabled by configuration")
    elif health.state in {"missing", "corrupt"}:
        index_check = _check("index", "FAIL", health.message)
    else:
        index_check = _check(
            "index",
            "PASS",
            str(context.paths.state / "index.sqlite"),
        )
    dirty_check = _check(
        "index_dirty",
        "WARN" if health.state == "dirty" else "PASS",
        "index rebuild required" if health.state == "dirty" else "clean",
    )
    stale_check = _check(
        "index_stale",
        "WARN" if health.state == "stale" else "PASS",
        health.message if health.state == "stale" else "current",
    )
    return [index_check, dirty_check, stale_check]


def _source_checks(
    snapshot: RepositorySnapshot,
    report: ValidationReport,
) -> list[DoctorCheck]:
    invalid = [source.relative_path for source in snapshot.invalid_sources]
    duplicates = sorted(snapshot.duplicate_ids)
    asset_errors = sum(
        issue.severity == "error" and issue.code in ASSET_ERROR_CODES for issue in report.issues
    )
    return [
        _check(
            "source_files",
            "FAIL" if invalid else "PASS",
            ", ".join(invalid) if invalid else "all parseable",
        ),
        _check(
            "duplicate_ids",
            "FAIL" if duplicates else "PASS",
            ", ".join(duplicates) if duplicates else "none",
        ),
        _check(
            "asset_integrity",
            "FAIL" if asset_errors else "PASS",
            f"{asset_errors} error(s)",
        ),
    ]
