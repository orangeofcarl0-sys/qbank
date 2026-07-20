"""Compatibility coordination between logical assets and question Markdown."""

from __future__ import annotations

from qbank.application.assets import AssetApplicationService
from qbank.assets import replace_image_uris
from qbank.context import ProjectContext
from qbank.domain import asset_legacy_references
from qbank.models import (
    QUESTION_CONTENT_FIELDS,
    AssetManifest,
    AssetNormalizeResult,
    Question,
    QuestionPatch,
)
from qbank.operations import MutationServices, apply_patch_in_context


def normalize_asset_references_in_context(
    context: ProjectContext,
    question_id: str,
    *,
    assets: AssetApplicationService,
    mutations: MutationServices,
    asset_id: str | None = None,
    dry_run: bool,
) -> AssetNormalizeResult:
    """Replace preserved legacy image paths with stable ``asset:`` references."""
    snapshot = mutations.repository.scan()
    snapshot.require_consistent()
    question = snapshot.locate(question_id).question
    manifests = [
        manifest
        for manifest in assets.repository.list(question_id)
        if asset_id is None or manifest.asset_id == asset_id
    ]
    updated = _normalized_question(question, manifests)
    fields = _changed_fields(question, updated)
    if not fields:
        return AssetNormalizeResult(
            ok=True,
            dry_run=dry_run,
            question_id=question_id,
            assets=[item.asset_id for item in manifests],
            changed=False,
            changes=[],
            warnings=[],
            index_updated=False,
        )
    result = apply_patch_in_context(
        context,
        question_id,
        QuestionPatch(set=fields),
        services=mutations,
        dry_run=dry_run,
        command="qbank asset normalize",
    )
    return AssetNormalizeResult(
        ok=result.ok,
        dry_run=dry_run,
        question_id=question_id,
        assets=[item.asset_id for item in manifests],
        changed=True,
        changes=result.changes,
        warnings=result.warnings,
        index_updated=result.index_updated,
    )


def _normalized_question(
    question: Question,
    manifests: list[AssetManifest],
) -> Question:
    replacements: dict[str, str] = {}
    declarations = list(question.assets)
    content = {field: getattr(question, field) for field in QUESTION_CONTENT_FIELDS}
    for manifest in manifests:
        canonical = f"asset:{manifest.asset_id}"
        legacy = asset_legacy_references(manifest.provenance)
        replacements.update({item: canonical for item in legacy})
        declarations = [canonical if item in legacy else item for item in declarations]
        placeholder = manifest.provenance.get("markdown_placeholder")
        field = manifest.provenance.get("content_field")
        if (
            isinstance(placeholder, str)
            and isinstance(field, str)
            and field in content
            and placeholder in content[field]
        ):
            alt = manifest.provenance.get("alt", manifest.role)
            content[field] = content[field].replace(
                placeholder,
                f"![{alt}](asset:{manifest.asset_id})",
            )
            declarations.append(canonical)
    for field, value in content.items():
        content[field] = replace_image_uris(value, replacements)
    values = question.model_dump(mode="python")
    values.update(content)
    values["assets"] = list(dict.fromkeys(declarations))
    return Question.model_validate(values)


def _changed_fields(previous: Question, current: Question) -> dict[str, object]:
    return {
        field: getattr(current, field)
        for field in ("assets", *QUESTION_CONTENT_FIELDS)
        if getattr(previous, field) != getattr(current, field)
    }
