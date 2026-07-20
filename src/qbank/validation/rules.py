"""Deterministic, independently testable question validation rules."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from pydantic import ValidationError
from ruamel.yaml.error import YAMLError

from qbank.asset_references import (
    AssetKind,
    AssetReference,
    classify_resource_uri,
    extract_image_resources,
)
from qbank.models import (
    QUESTION_CONTENT_FIELDS,
    AssetManifest,
    ProjectConfig,
    Question,
    QuestionStatus,
    QuestionType,
    ValidationIssue,
    extract_option_labels,
)
from qbank.question_layout import QUESTION_CONTENT_FIELDS as ORDERED_CONTENT_FIELDS
from qbank.utils import is_relative_to
from qbank.validation.common import (
    QuestionValidationContext,
    issue,
    latex_issues,
)
from qbank.yaml_io import load_yaml

ValidationRule = Callable[[QuestionValidationContext], list[ValidationIssue]]


def identity_rule(
    context: QuestionValidationContext,
) -> list[ValidationIssue]:
    """Validate the filename-to-ID invariant."""
    if context.path.stem == context.question.id:
        return []
    return [
        issue(
            "error",
            "filename_id_mismatch",
            f"filename {context.path.name} must equal {context.question.id}.md",
            context=context,
            field="id",
        )
    ]


def status_rule(
    context: QuestionValidationContext,
) -> list[ValidationIssue]:
    """Validate answer requirements and deprecation information."""
    question = context.question
    issues: list[ValidationIssue] = []
    if (
        question.status in {QuestionStatus.REVIEWED, QuestionStatus.VERIFIED}
        and not question.answer_md.strip()
    ):
        issues.append(
            issue(
                "error",
                "missing_reviewed_answer",
                f"{question.status.value} question must include an answer",
                context=context,
                field="answer_md",
            )
        )
    if question.status == QuestionStatus.DEPRECATED:
        issues.append(
            issue(
                "info",
                "deprecated_question",
                "deprecated question is retained for history",
                context=context,
                field="status",
            )
        )
    return issues


def choice_rule(
    context: QuestionValidationContext,
) -> list[ValidationIssue]:
    """Validate choice options and basic answer labels."""
    question = context.question
    issues: list[ValidationIssue] = []
    choice_types = {
        QuestionType.SINGLE_CHOICE,
        QuestionType.MULTIPLE_CHOICE,
    }
    if question.type in choice_types and not question.options_md.strip():
        issues.append(
            issue(
                "error",
                "missing_options",
                "choice question must include options",
                context=context,
                field="options_md",
            )
        )
        return issues
    labels = extract_option_labels(question.options_md)
    if not question.answer_md.strip() or not labels:
        return issues
    answers = set(re.findall(r"\b([A-Z])\b", question.answer_md.upper()))
    if question.type == QuestionType.SINGLE_CHOICE and (
        not answers or not answers <= labels or len(answers) != 1
    ):
        issues.append(
            issue(
                "warning",
                "single_choice_answer_mismatch",
                "single-choice answer should name exactly one available option",
                context=context,
                field="answer_md",
            )
        )
    if question.type == QuestionType.MULTIPLE_CHOICE and (
        len(answers) < 2 or not answers <= labels
    ):
        issues.append(
            issue(
                "warning",
                "multiple_choice_answer_format",
                "multiple-choice answer should name two or more available options",
                context=context,
                field="answer_md",
            )
        )
    return issues


def structure_rule(
    context: QuestionValidationContext,
) -> list[ValidationIssue]:
    """Validate duplicate sections and long fields in front matter."""
    issues = [
        issue(
            "error",
            "duplicate_section",
            f"duplicate Markdown section: {name}",
            context=context,
        )
        for name in context.duplicate_sections
    ]
    disallowed = sorted(context.metadata_fields & set(QUESTION_CONTENT_FIELDS))
    issues.extend(
        issue(
            "error",
            "content_in_yaml",
            f"long content field must be in a Markdown section: {name}",
            context=context,
            field=name,
        )
        for name in disallowed
    )
    return issues


def asset_rule(
    context: QuestionValidationContext,
) -> list[ValidationIssue]:
    """Validate declared assets and Markdown image references bidirectionally."""
    declared, declared_issues = _declared_assets(context)
    referenced, reference_issues = _referenced_assets(context, declared)
    unused_issues = [
        issue(
            "warning",
            "unused_asset",
            f"YAML asset is not referenced by Markdown: {unused}",
            context=context,
            field="assets",
        )
        for unused in sorted(declared - referenced)
    ]
    return [*declared_issues, *reference_issues, *unused_issues]


def _declared_assets(
    context: QuestionValidationContext,
) -> tuple[set[str], list[ValidationIssue]]:
    declared: set[str] = set()
    issues: list[ValidationIssue] = []
    for raw in context.question.assets:
        reference = classify_resource_uri(raw)
        if reference.kind == AssetKind.LOGICAL and reference.normalized is not None:
            declared.add(reference.normalized)
            issues.extend(_logical_asset_issues(context, reference, field="assets"))
            continue
        if reference.kind != AssetKind.LOCAL or reference.normalized is None:
            issues.append(
                issue(
                    "error",
                    "invalid_resource_uri",
                    f"YAML asset must be a local project-relative path: {raw}",
                    context=context,
                    field="assets",
                )
            )
            if ".." in PurePosixPath(raw.replace("\\", "/")).parts:
                issues.append(
                    issue(
                        "error",
                        "asset_path_escape",
                        f"asset path escapes project root: {raw}",
                        context=context,
                        field="assets",
                    )
                )
            continue
        declared.add(reference.normalized)
        issues.extend(
            _local_asset_issues(
                context,
                reference.normalized,
                raw,
                field="assets",
                outside_code="asset_outside_assets",
            )
        )
    return declared, issues


def _referenced_assets(
    context: QuestionValidationContext,
    declared: set[str],
) -> tuple[set[str], list[ValidationIssue]]:
    referenced: set[str] = set()
    issues: list[ValidationIssue] = []
    for raw, fields in extract_image_resources(context.question).items():
        reference = classify_resource_uri(raw)
        field = ",".join(sorted(fields))
        if reference.kind == AssetKind.EXTERNAL:
            issues.append(
                issue(
                    "warning",
                    "external_asset",
                    f"external image resource is not stored locally: {raw}",
                    context=context,
                    field=field,
                )
            )
            continue
        if reference.kind == AssetKind.LOGICAL and reference.normalized is not None:
            referenced.add(reference.normalized)
            issues.extend(_logical_asset_issues(context, reference, field=field))
            if reference.normalized not in declared:
                issues.append(
                    issue(
                        "error",
                        "undeclared_asset_reference",
                        f"Markdown logical asset is missing from YAML assets: {raw}",
                        context=context,
                        field=field,
                    )
                )
            continue
        if reference.kind == AssetKind.INVALID or reference.normalized is None:
            issues.append(
                issue(
                    "error",
                    "invalid_resource_uri",
                    f"invalid image resource URI: {raw}",
                    context=context,
                    field=field,
                )
            )
            continue
        referenced.add(reference.normalized)
        issues.extend(
            _local_asset_issues(
                context,
                reference.normalized,
                raw,
                field=field,
                outside_code="invalid_resource_uri",
            )
        )
        if reference.normalized not in declared:
            issues.append(
                issue(
                    "error",
                    "undeclared_asset_reference",
                    f"Markdown image is missing from YAML assets: {raw}",
                    context=context,
                    field=field,
                )
            )
    return referenced, issues


def _local_asset_issues(
    context: QuestionValidationContext,
    normalized: str,
    raw: str,
    *,
    field: str,
    outside_code: str,
) -> list[ValidationIssue]:
    candidate = (context.root.resolve() / normalized).resolve()
    assets_root = (context.root.resolve() / context.config.paths.assets).resolve()
    if not is_relative_to(candidate, context.root.resolve()):
        return [
            issue(
                "error",
                "asset_path_escape",
                f"asset path escapes project root: {raw}",
                context=context,
                field=field,
            )
        ]
    if not is_relative_to(candidate, assets_root):
        message = (
            f"asset must be stored under {context.config.paths.assets}: {raw}"
            if outside_code == "asset_outside_assets"
            else f"local image must be under {context.config.paths.assets}: {raw}"
        )
        return [
            issue(
                "error",
                outside_code,
                message,
                context=context,
                field=field,
            )
        ]
    if not candidate.is_file():
        return [
            issue(
                "error",
                "asset_missing",
                f"asset does not exist: {raw}",
                context=context,
                field=field,
            )
        ]
    return []


def _logical_asset_issues(
    context: QuestionValidationContext,
    reference: AssetReference,
    *,
    field: str,
) -> list[ValidationIssue]:
    if reference.asset_id is None:
        return [
            issue(
                "error",
                "invalid_resource_uri",
                "invalid logical asset reference",
                context=context,
                field=field,
            )
        ]
    manifest_path = (
        context.root.resolve()
        / context.config.paths.assets
        / context.question.id
        / reference.asset_id
        / "asset.yaml"
    )
    if not manifest_path.is_file():
        return [
            issue(
                "error",
                "asset_not_found",
                f"asset_not_found: asset does not exist: {context.question.id}/{reference.asset_id}",
                context=context,
                field=field,
            )
        ]
    try:
        raw = load_yaml(manifest_path.read_text(encoding="utf-8"))
        manifest = AssetManifest.model_validate(raw)
    except (OSError, UnicodeError, YAMLError, ValidationError, ValueError) as exc:
        return [
            issue(
                "error",
                "asset_manifest_invalid",
                f"asset_manifest_invalid: {manifest_path.relative_to(context.root)}: {exc}",
                context=context,
                field=field,
            )
        ]
    if manifest.question_id != context.question.id or manifest.asset_id != reference.asset_id:
        return [
            issue(
                "error",
                "asset_manifest_invalid",
                f"asset_manifest_invalid: identity does not match {context.question.id}/{reference.asset_id}",
                context=context,
                field=field,
            )
        ]
    if reference.representation_id is not None and not any(
        item.representation_id == reference.representation_id for item in manifest.representations
    ):
        return [
            issue(
                "error",
                "asset_representation_missing",
                f"asset_representation_missing: {reference.representation_id}",
                context=context,
                field=field,
            )
        ]
    return []


def latex_rule(
    context: QuestionValidationContext,
) -> list[ValidationIssue]:
    """Run lightweight LaTeX checks in canonical field order."""
    return [
        issue_item
        for field in ORDERED_CONTENT_FIELDS
        for issue_item in latex_issues(
            getattr(context.question, field),
            context=context,
            field=field,
        )
    ]


QUESTION_RULES: tuple[ValidationRule, ...] = (
    identity_rule,
    status_rule,
    choice_rule,
    structure_rule,
    asset_rule,
    latex_rule,
)


def validate_question(
    root: Path,
    config: ProjectConfig,
    path: Path,
    question: Question,
    *,
    duplicates: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> list[ValidationIssue]:
    """Apply every semantic rule in fixed deterministic order."""
    context = QuestionValidationContext(
        root=root,
        config=config,
        path=path,
        question=question,
        duplicate_sections=tuple(duplicates or ()),
        metadata_fields=frozenset((metadata or {}).keys()),
    )
    return [diagnostic for rule in QUESTION_RULES for diagnostic in rule(context)]
