"""Interactive Studio save: question, taxonomy, history, and index in one command."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from qbank.application.ports import MutableTaxonomyStorePort
from qbank.application.revision import repository_revision
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord, QuestionRecord, RepositorySnapshot
from qbank.errors import ConflictError
from qbank.models import (
    Diagnostic,
    FieldChange,
    PatchQuestionResult,
    Question,
    QuestionPatch,
    TagStatus,
    Taxonomy,
    TaxonomyTag,
    normalize_tag_slug,
)
from qbank.operations.common import (
    MutationServices,
    aggregate_hash,
    ensure_sources_are_consistent,
    question_diagnostics,
    require_repository_revision,
    sync_index_after_commit,
    write_history_record,
    write_lock,
)
from qbank.operations.patch import diff_questions, patched_question
from qbank.storage import prepare_question_for_write, render_question
from qbank.transaction import MutationTransaction


@dataclass(frozen=True, slots=True)
class StudioSavePlan:
    """Fully validated question, taxonomy, history, and index save plan."""

    snapshot: RepositorySnapshot
    previous: QuestionRecord
    prepared: Question
    destination: Path
    rendered: str
    changes: tuple[FieldChange, ...]
    taxonomy_before: Taxonomy
    taxonomy_after: Taxonomy
    repository_revision: str


@dataclass(frozen=True, slots=True)
class StudioSaveRequest:
    """Named inputs for one interactive save command."""

    question_id: str
    patch: QuestionPatch
    dry_run: bool
    command: str


def save_studio_question_in_context(
    context: ProjectContext,
    request: StudioSaveRequest,
    *,
    services: MutationServices,
    taxonomy: MutableTaxonomyStorePort,
) -> PatchQuestionResult:
    """Save question, pending taxonomy, history, and index through one command."""
    result, plan = _plan_studio_save(
        context,
        request.question_id,
        request.patch,
        services=services,
        taxonomy=taxonomy,
        dry_run=request.dry_run,
    )
    if request.dry_run or plan is None:
        return result
    _commit_studio_save(context, plan, result, services, taxonomy, request.command)
    return result


def _plan_studio_save(
    context: ProjectContext,
    question_id: str,
    patch: QuestionPatch,
    *,
    services: MutationServices,
    taxonomy: MutableTaxonomyStorePort,
    dry_run: bool,
) -> tuple[PatchQuestionResult, StudioSavePlan | None]:
    expected_revision = repository_revision(context)
    snapshot = services.repository.scan()
    ensure_sources_are_consistent(snapshot)
    previous = snapshot.locate(question_id)
    candidate = patched_question(previous.question, patch)
    errors, warnings = question_diagnostics(
        context.root,
        context.config,
        candidate,
        services.repository.destination(candidate),
    )
    if errors:
        return _patch_result(question_id, dry_run, (), errors, warnings), None
    taxonomy_before = taxonomy.load()
    taxonomy_after = _taxonomy_with_pending(taxonomy_before, candidate.topics)
    if candidate == previous.question and taxonomy_before == taxonomy_after:
        return _patch_result(question_id, dry_run, (), (), warnings), None
    prepared = prepare_question_for_write(candidate, previous=previous.question)
    changes = tuple(
        change
        for change in diff_questions(previous.question, prepared)
        if change.field != "updated_at"
    )
    plan = StudioSavePlan(
        snapshot=snapshot,
        previous=previous,
        prepared=prepared,
        destination=services.repository.destination(prepared),
        rendered=render_question(prepared),
        changes=changes,
        taxonomy_before=taxonomy_before,
        taxonomy_after=taxonomy_after,
        repository_revision=expected_revision,
    )
    return _patch_result(question_id, dry_run, changes, (), warnings), plan


def _patch_result(
    question_id: str,
    dry_run: bool,
    changes: Sequence[FieldChange],
    errors: Sequence[Diagnostic],
    warnings: Sequence[Diagnostic],
) -> PatchQuestionResult:
    return PatchQuestionResult(
        ok=not errors,
        id=question_id,
        dry_run=dry_run,
        changes=list(changes),
        validation_errors=list(errors),
        validation_warnings=list(warnings),
        warnings=list(warnings),
        index_updated=False,
    )


def _taxonomy_with_pending(taxonomy: Taxonomy, topics: Sequence[str]) -> Taxonomy:
    tags = list(taxonomy.tags)
    known = taxonomy.by_slug()
    for value in topics:
        canonical = taxonomy.resolve(value) or normalize_tag_slug(value)
        if canonical not in known:
            pending = TaxonomyTag(slug=canonical, status=TagStatus.PENDING)
            tags.append(pending)
            known[canonical] = pending
    return Taxonomy(tags=sorted(tags, key=lambda item: item.slug))


def _commit_studio_save(
    context: ProjectContext,
    plan: StudioSavePlan,
    result: PatchQuestionResult,
    services: MutationServices,
    taxonomy: MutableTaxonomyStorePort,
    command: str,
) -> None:
    with write_lock(context, services).hold(command):
        require_repository_revision(context, plan.repository_revision)
        if plan.previous.path.read_text(encoding="utf-8") != plan.previous.text:
            raise ConflictError(f"question changed during Studio save: {plan.prepared.id}")
        if taxonomy.load() != plan.taxonomy_before:
            raise ConflictError("taxonomy.yaml changed during Studio save")
        transaction = MutationTransaction.for_context(context)
        transaction.write(plan.destination, plan.rendered)
        if plan.previous.path != plan.destination:
            transaction.delete(plan.previous.path)
        taxonomy_changed = plan.taxonomy_before != plan.taxonomy_after
        if taxonomy_changed:
            transaction.write(taxonomy.path, taxonomy.text(plan.taxonomy_after))
        write_history_record(transaction, services.history, _studio_history(plan, taxonomy, command))
        transaction.commit()
        result.index_updated, index_warnings = sync_index_after_commit(
            context,
            services.index,
            snapshot=plan.snapshot,
            questions=[plan.prepared],
        )
        result.warnings.extend(index_warnings)


def _studio_history(
    plan: StudioSavePlan,
    taxonomy: MutableTaxonomyStorePort,
    command: str,
) -> HistoryRecord:
    changes = tuple(change.model_dump(mode="json", exclude_none=True) for change in plan.changes)
    if plan.taxonomy_before != plan.taxonomy_after:
        before_slugs = set(plan.taxonomy_before.by_slug())
        added = [tag.slug for tag in plan.taxonomy_after.tags if tag.slug not in before_slugs]
        changes += ({"kind": "taxonomy_pending", "field": "topics", "new": added},)
    before = {
        plan.prepared.id: plan.previous.text,
        "taxonomy.yaml": taxonomy.text(plan.taxonomy_before),
    }
    after = {
        plan.prepared.id: plan.rendered,
        "taxonomy.yaml": taxonomy.text(plan.taxonomy_after),
    }
    return HistoryRecord(
        operation="studio_save",
        question_ids=(plan.prepared.id,),
        command=command,
        dry_run=False,
        before_hash=aggregate_hash(before),
        after_hash=aggregate_hash(after),
        changes=changes,
    )
