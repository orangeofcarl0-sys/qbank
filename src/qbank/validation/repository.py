"""Repository-level validation orchestration and parser diagnostics."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError
from ruamel.yaml.error import YAMLError

from qbank.context import ProjectContext
from qbank.models import (
    ProjectConfig,
    Question,
    ValidationIssue,
    ValidationReport,
    ValidationSummary,
)
from qbank.repository import (
    InvalidQuestionSource,
    MarkdownQuestionRepository,
    QuestionRecord,
    RepositorySnapshot,
)
from qbank.storage import (
    MarkdownParseError,
    parse_question_file,
    parse_sections,
    split_frontmatter,
)
from qbank.validation.common import IssueLocation, issue
from qbank.validation.rules import validate_question
from qbank.yaml_io import load_yaml


def validate_file(
    root: Path,
    config: ProjectConfig,
    path: Path,
) -> tuple[Question | None, list[ValidationIssue]]:
    """Validate one file, normalizing parser and Pydantic failures."""
    try:
        question, duplicates, metadata = parse_question_file(path)
    except MarkdownParseError as exc:
        source = InvalidQuestionSource(
            path=path,
            relative_path=path.relative_to(root).as_posix(),
            error=str(exc),
            filename_id=path.stem,
            frontmatter_id=None,
        )
        return None, invalid_source_issues(root, source)
    return question, validate_question(
        root,
        config,
        path,
        question,
        duplicates=duplicates,
        metadata=metadata,
    )


def changed_files(
    context: ProjectContext,
    repository: MarkdownQuestionRepository,
) -> tuple[Path, ...]:
    """Return changed question files, falling back to all files without Git."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=context.root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return repository.source_paths()
    if result.returncode:
        return repository.source_paths()
    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        relative = line[3:].strip().strip('"').replace("\\", "/")
        candidate = (context.root / relative).resolve()
        if (
            candidate.suffix.lower() == ".md"
            and candidate.is_file()
            and candidate.is_relative_to(context.paths.questions)
        ):
            paths.add(candidate)
    return tuple(sorted(paths, key=lambda path: str(path)))


def validate_repository_in_context(
    context: ProjectContext,
    *,
    question_id: str | None = None,
    changed: bool = False,
    snapshot: RepositorySnapshot | None = None,
) -> ValidationReport:
    """Validate selected or all repository sources from one snapshot."""
    root, config = context.root, context.config
    repository = MarkdownQuestionRepository(context)
    if snapshot is None:
        paths = changed_files(context, repository) if changed else None
        snapshot = repository.scan(paths)
    selected_paths, selected_records, issues = _selected_diagnostics(
        root,
        config,
        snapshot,
        question_id,
    )
    if question_id and not selected_paths:
        issues.append(
            issue(
                "error",
                "question_not_found",
                f"question not found: {question_id}",
                location=IssueLocation(
                    root=root,
                    question_id=question_id,
                ),
            )
        )
    issues.extend(_duplicate_issues(root, selected_records))
    errors = sum(item.severity == "error" for item in issues)
    warnings = sum(item.severity == "warning" for item in issues)
    info_count = sum(item.severity == "info" for item in issues)
    return ValidationReport(
        ok=errors == 0,
        summary=ValidationSummary(
            questions=len(selected_paths),
            errors=errors,
            warnings=warnings,
            info=info_count,
        ),
        issues=issues,
    )


def validate_repository(
    root: Path,
    config: ProjectConfig,
    *,
    question_id: str | None = None,
    changed: bool = False,
    snapshot: RepositorySnapshot | None = None,
) -> ValidationReport:
    """Compatibility adapter for context-based repository validation."""
    return validate_repository_in_context(
        ProjectContext.from_config(root, config),
        question_id=question_id,
        changed=changed,
        snapshot=snapshot,
    )


def _selected_diagnostics(
    root: Path,
    config: ProjectConfig,
    snapshot: RepositorySnapshot,
    question_id: str | None,
) -> tuple[list[Path], list[QuestionRecord], list[ValidationIssue]]:
    selected_paths: list[Path] = []
    selected_records: list[QuestionRecord] = []
    issues: list[ValidationIssue] = []
    for source in snapshot.invalid_sources:
        if question_id is None or source.matches(question_id):
            selected_paths.append(source.path)
            issues.extend(invalid_source_issues(root, source))
    for record in snapshot.records:
        matches = (
            question_id is None
            or record.path.stem == question_id
            or record.question.id == question_id
        )
        if not matches:
            continue
        selected_paths.append(record.path)
        selected_records.append(record)
        issues.extend(
            validate_question(
                root,
                config,
                record.path,
                record.question,
                duplicates=list(record.duplicate_sections),
                metadata=record.metadata,
            )
        )
    return selected_paths, selected_records, issues


def _duplicate_issues(
    root: Path,
    records: list[QuestionRecord],
) -> list[ValidationIssue]:
    counts = Counter(record.question.id for record in records)
    return [
        issue(
            "error",
            "duplicate_id",
            f"question ID occurs {counts[record.question.id]} times",
            location=IssueLocation(
                root=root,
                path=record.path,
                question_id=record.question.id,
            ),
            field="id",
        )
        for record in records
        if counts[record.question.id] > 1
    ]


def invalid_source_issues(
    root: Path,
    source: InvalidQuestionSource,
) -> list[ValidationIssue]:
    """Map one parser failure to stable source diagnostics."""
    issues = [
        issue(
            "error",
            "invalid_source_file",
            source.error,
            location=IssueLocation(root=root, path=source.path),
        )
    ]
    if (
        "created_at" in source.error or "updated_at" in source.error
    ) and "timestamp" in source.error:
        issues.append(
            issue(
                "error",
                "invalid_timestamp",
                source.error,
                location=IssueLocation(root=root, path=source.path),
                field="created_at/updated_at",
            )
        )
    if "stem_md" in source.error and (
        "must not be empty" in source.error or "Field required" in source.error
    ):
        issues.append(
            issue(
                "error",
                "empty_stem",
                "题目 section must be non-empty",
                location=IssueLocation(root=root, path=source.path),
                field="stem_md",
            )
        )
    return issues


def validate_raw_question(
    root: Path,
    config: ProjectConfig,
    raw: dict[str, Any],
) -> tuple[Question | None, list[ValidationIssue]]:
    """Validate an exchange object before it is written."""
    try:
        question = Question.model_validate(raw)
    except ValidationError as exc:
        issues = [
            issue(
                "error",
                (
                    "invalid_timestamp"
                    if error["loc"] and str(error["loc"][-1]) in {"created_at", "updated_at"}
                    else "model_validation"
                ),
                error["msg"],
                location=IssueLocation(root=root),
                field=".".join(str(part) for part in error["loc"]),
            )
            for error in exc.errors()
        ]
        return None, issues
    destination = (
        ProjectContext.from_config(root, config).paths.questions
        / question.subject
        / f"{question.id}.md"
    )
    return question, validate_question(
        root,
        config,
        destination,
        question,
    )


def inspect_frontmatter(
    path: Path,
) -> tuple[dict[str, Any] | None, str | None]:
    """Best-effort YAML inspection retained for compatibility."""
    try:
        yaml_text, body = split_frontmatter(path.read_text(encoding="utf-8"))
        metadata = load_yaml(yaml_text)
        parse_sections(body)
        return cast(dict[str, Any], metadata) if isinstance(metadata, dict) else None, None
    except (
        OSError,
        UnicodeError,
        YAMLError,
        MarkdownParseError,
    ) as exc:
        return None, str(exc)
