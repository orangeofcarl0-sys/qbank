"""Shared validation context and diagnostic constructors."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from qbank.models import DiagnosticCode, ProjectConfig, Question, ValidationIssue
from qbank.models.results import Severity


@dataclass(frozen=True, slots=True)
class QuestionValidationContext:
    """Immutable inputs supplied to every question rule."""

    root: Path
    config: ProjectConfig
    path: Path
    question: Question
    duplicate_sections: tuple[str, ...] = ()
    metadata_fields: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class IssueLocation:
    """Source location for diagnostics created without a valid question."""

    root: Path
    path: Path | None = None
    question_id: str | None = None


def issue(
    severity: Severity,
    code: DiagnosticCode | str,
    message: str,
    *,
    context: QuestionValidationContext | None = None,
    location: IssueLocation | None = None,
    field: str | None = None,
) -> ValidationIssue:
    """Build one normalized diagnostic."""
    if context is not None:
        root = context.root
        path = context.path
        question_id = context.question.id
    elif location is not None:
        root = location.root
        path = location.path
        question_id = location.question_id
    else:
        raise ValueError("validation issue requires a project root")
    return ValidationIssue(
        severity=severity,
        id=question_id,
        file=path.relative_to(root).as_posix() if path else None,
        field=field,
        code=DiagnosticCode(code),
        message=message,
    )


def latex_issues(
    text: str,
    *,
    context: QuestionValidationContext,
    field: str,
) -> list[ValidationIssue]:
    """Apply lightweight, non-compiling LaTeX delimiter checks."""
    issues: list[ValidationIssue] = []
    if text.replace(r"\$", "").count("$") % 2:
        issues.append(
            issue(
                "warning",
                "latex_dollar_unbalanced",
                "possibly unmatched $",
                context=context,
                field=field,
            )
        )
    for opening, closing in ((r"\(", r"\)"), (r"\[", r"\]")):
        if text.count(opening) != text.count(closing):
            issues.append(
                issue(
                    "warning",
                    "latex_delimiter_unbalanced",
                    f"unbalanced {opening} and {closing}",
                    context=context,
                    field=field,
                )
            )
    cleaned = re.sub(r"\\[{}]", "", text)
    if cleaned.count("{") != cleaned.count("}"):
        issues.append(
            issue(
                "warning",
                "latex_brace_unbalanced",
                "possibly unbalanced LaTeX braces",
                context=context,
                field=field,
            )
        )
    return issues
