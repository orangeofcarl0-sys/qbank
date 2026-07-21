"""Concrete atomic commit adapter for project-level tag operations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from qbank.application.tags import TagMutationPlan
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord, RepositorySnapshot
from qbank.errors import ConflictError, DataValidationError, QuestionNotFoundError
from qbank.models import (
    Diagnostic,
    DiagnosticCode,
    Question,
    TagMutationResult,
    TagQuestionChange,
    Taxonomy,
)
from qbank.operations import MutationServices
from qbank.storage import prepare_question_for_write, render_question
from qbank.taxonomy_store import YamlTaxonomyStore
from qbank.transaction import MutationTransaction
from qbank.utils import sha256_text
from qbank.validation import validate_question


@dataclass(frozen=True, slots=True)
class TagUndoRecord:
    """Validated reversible state extracted from a tag history entry."""

    taxonomy_before: Taxonomy
    taxonomy_after: Taxonomy
    question_changes: tuple[dict[str, Any], ...]


class AtomicTagMutationExecutor:
    """Commit taxonomy, affected Markdown, and history as one authority unit."""

    def __init__(self, context: ProjectContext, services: MutationServices):
        self.context = context
        self.services = services
        self.taxonomy = YamlTaxonomyStore(context)

    def commit(self, plan: TagMutationPlan) -> TagMutationResult:
        """Validate the complete plan, then commit or return its dry-run diff."""
        plan.snapshot.require_consistent()
        current_taxonomy = self.taxonomy.load()
        if current_taxonomy != plan.taxonomy_before:
            raise ConflictError("taxonomy.yaml changed while the tag operation was being planned")
        prepared = self._prepare_questions(plan)
        result = TagMutationResult(
            ok=True,
            dry_run=plan.dry_run,
            operation=plan.operation,
            affected_questions=len(plan.changes),
            changes=list(plan.changes),
            taxonomy_before=plan.taxonomy_before.tags,
            taxonomy_after=plan.taxonomy_after.tags,
            history_token=None,
            warnings=[],
            index_updated=False,
        )
        if plan.dry_run:
            return result
        taxonomy_changed = plan.taxonomy_before != plan.taxonomy_after
        if not prepared and not taxonomy_changed:
            return result
        transaction = MutationTransaction()
        before: dict[str, str] = {}
        after: dict[str, str] = {}
        for question in prepared:
            record = plan.snapshot.locate(question.id)
            if record.path.read_text(encoding="utf-8") != record.text:
                raise ConflictError(f"question changed during tag operation: {question.id}")
            rendered = render_question(question)
            transaction.write(record.path, rendered)
            before[question.id] = record.text
            after[question.id] = rendered
        if taxonomy_changed:
            transaction.write(self.taxonomy.path, self.taxonomy.text(plan.taxonomy_after))
        history_path, history_text = self.services.history.prepare(
            HistoryRecord(
                operation=plan.operation,
                question_ids=tuple(change.id for change in plan.changes),
                command=plan.command,
                dry_run=False,
                before_hash=_aggregate_hash(before, self.taxonomy.text(plan.taxonomy_before)),
                after_hash=_aggregate_hash(after, self.taxonomy.text(plan.taxonomy_after)),
                changes=(
                    {
                        "kind": "taxonomy",
                        "before": plan.taxonomy_before.model_dump(mode="json"),
                        "after": plan.taxonomy_after.model_dump(mode="json"),
                    },
                    *(
                        {
                            "kind": "question_topics",
                            **change.model_dump(mode="json"),
                        }
                        for change in plan.changes
                    ),
                ),
            )
        )
        transaction.write(history_path, history_text)
        transaction.commit()
        result.history_token = history_path.stem
        if prepared:
            result.index_updated, result.warnings = self._sync_index(
                prepared,
                plan.snapshot,
            )
        return result

    def undo(self, token: str, *, dry_run: bool, command: str) -> TagMutationResult:
        """Build and apply an inverse plan from one durable tag history event."""
        undo = self._load_undo_record(token)
        current = self.taxonomy.load()
        if current != undo.taxonomy_after:
            raise ConflictError("taxonomy changed after this history event; undo is unsafe")
        snapshot = self.services.repository.scan()
        snapshot.require_consistent()
        questions, changes = self._inverse_questions(snapshot, undo.question_changes)
        return self.commit(
            TagMutationPlan(
                snapshot=snapshot,
                taxonomy_before=current,
                taxonomy_after=undo.taxonomy_before,
                questions=questions,
                changes=changes,
                operation="tag_undo",
                command=command,
                dry_run=dry_run,
            )
        )

    def _load_undo_record(self, token: str) -> TagUndoRecord:
        path = self.context.paths.state / "history" / f"{token}.json"
        if not path.is_file():
            raise QuestionNotFoundError(f"tag history not found: {token}")
        try:
            payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
            raw_changes = cast(list[dict[str, Any]], payload["changes"])
            taxonomy_change = next(
                change for change in raw_changes if change.get("kind") == "taxonomy"
            )
            return TagUndoRecord(
                taxonomy_before=Taxonomy.model_validate(taxonomy_change["before"]),
                taxonomy_after=Taxonomy.model_validate(taxonomy_change["after"]),
                question_changes=tuple(
                    change for change in raw_changes if change.get("kind") == "question_topics"
                ),
            )
        except (OSError, UnicodeError, ValueError, KeyError, StopIteration, TypeError) as exc:
            raise DataValidationError(f"invalid tag history record: {path.name}") from exc

    def _inverse_questions(
        self,
        snapshot: RepositorySnapshot,
        raw_changes: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[Question, ...], tuple[TagQuestionChange, ...]]:
        questions: list[Question] = []
        changes: list[TagQuestionChange] = []
        for raw in raw_changes:
            record = snapshot.locate(str(raw["id"]))
            expected = [str(topic) for topic in cast(list[object], raw["after"])]
            restored = [str(topic) for topic in cast(list[object], raw["before"])]
            if record.question.topics != expected:
                raise ConflictError(
                    f"question topics changed after history event: {record.question.id}"
                )
            values = record.question.model_dump()
            values["topics"] = restored
            questions.append(Question.model_validate(values))
            changes.append(
                TagQuestionChange(id=record.question.id, before=expected, after=restored)
            )
        return tuple(questions), tuple(changes)

    def _prepare_questions(self, plan: TagMutationPlan) -> list[Question]:
        prepared: list[Question] = []
        for candidate in plan.questions:
            previous = plan.snapshot.locate(candidate.id).question
            question = prepare_question_for_write(candidate, previous=previous)
            issues = validate_question(
                self.context.root,
                self.context.config,
                self.services.repository.destination(question),
                question,
            )
            errors = [issue for issue in issues if issue.severity == "error"]
            if errors:
                details = json.dumps(
                    [error.model_dump(mode="json", exclude_none=True) for error in errors],
                    ensure_ascii=False,
                )
                raise DataValidationError(details)
            prepared.append(question)
        return prepared

    def _sync_index(
        self,
        questions: Sequence[Question],
        snapshot: RepositorySnapshot,
    ) -> tuple[bool, list[Diagnostic]]:
        if not self.context.config.index.enabled:
            return False, []
        try:
            topics_by_question = {
                record.question.id: tuple(record.question.topics) for record in snapshot.records
            }
            topics_by_question.update(
                {question.id: tuple(question.topics) for question in questions}
            )
            self.services.index.apply(
                questions=tuple(questions),
                topics_by_question=topics_by_question,
            )
        except Exception as exc:
            message = f"authoritative tag changes committed, but index update failed: {exc}"
            try:
                self.services.index.mark_dirty(message)
            except Exception as marker_exc:
                message += f"; dirty marker could not be written: {marker_exc}"
            return False, [
                Diagnostic(
                    severity="warning",
                    code=DiagnosticCode.INDEX_DIRTY,
                    message=message,
                )
            ]
        return True, []


def _aggregate_hash(files: dict[str, str], taxonomy_text: str) -> str:
    payload = {**files, "taxonomy.yaml": taxonomy_text}
    digest = sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if digest is None:
        raise RuntimeError("tag history hash unexpectedly missing")
    return digest
