"""Project-level tag taxonomy, statistics, and bulk topic use cases."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol

from qbank.application.ports import QuestionRepositoryPort
from qbank.domain import RepositorySnapshot
from qbank.errors import ConflictError, DataValidationError, QuestionNotFoundError
from qbank.models import (
    Question,
    TagCooccurrence,
    TagCoverageCell,
    TagMutationResult,
    TagOverviewResult,
    TagQuestionChange,
    TagStatus,
    TagUsage,
    Taxonomy,
    TaxonomyTag,
    normalize_tag_slug,
)


class TaxonomyStorePort(Protocol):
    """Read access to project tag display metadata."""

    def load(self) -> Taxonomy: ...


class TagMutationExecutorPort(Protocol):
    """Atomic taxonomy, Markdown, history, and index commit boundary."""

    def commit(self, plan: TagMutationPlan) -> TagMutationResult: ...

    def undo(self, token: str, *, dry_run: bool, command: str) -> TagMutationResult: ...


@dataclass(frozen=True, slots=True)
class TagMutationPlan:
    """A fully validated tag mutation ready for atomic persistence."""

    snapshot: RepositorySnapshot
    taxonomy_before: Taxonomy
    taxonomy_after: Taxonomy
    questions: tuple[Question, ...]
    changes: tuple[TagQuestionChange, ...]
    operation: str
    command: str
    dry_run: bool


@dataclass(frozen=True, slots=True)
class TagMutationMetadata:
    """Shared operation identity passed through topic planning helpers."""

    operation: str
    command: str
    dry_run: bool


@dataclass(frozen=True, slots=True)
class TagApplicationService:
    """Use authoritative question topics while augmenting them from a registry."""

    repository: QuestionRepositoryPort
    taxonomy: TaxonomyStorePort
    mutations: TagMutationExecutorPort

    def list_tags(self) -> list[TagUsage]:
        """List registered and unregistered tags with authoritative counts."""
        snapshot = self.repository.scan()
        snapshot.require_consistent()
        registry = self.taxonomy.load()
        counts = Counter(topic for record in snapshot.records for topic in record.question.topics)
        metadata = registry.by_slug()
        slugs = sorted(set(counts) | set(metadata))
        return [
            TagUsage(
                slug=slug,
                count=counts[slug],
                registered=slug in metadata,
                metadata=metadata.get(slug),
            )
            for slug in slugs
        ]

    def registry(self) -> Taxonomy:
        """Return tag display metadata without scanning question sources."""
        return self.taxonomy.load()

    def show_tag(self, value: str) -> TagUsage:
        """Resolve and show one registered slug, name, alias, or used topic."""
        registry = self.taxonomy.load()
        slug = registry.resolve(value) or value.strip()
        for item in self.list_tags():
            if item.slug == slug:
                return item
        raise QuestionNotFoundError(f"tag not found: {value}")

    def suggestions(self, text: str = "", *, limit: int = 20) -> list[TagUsage]:
        """Return autocomplete matches across names, slugs, and aliases."""
        query = text.strip().casefold()
        items = self.list_tags()
        if query:
            items = [
                item
                for item in items
                if query in item.slug.casefold()
                or (
                    item.metadata is not None
                    and any(query in term for term in item.metadata.search_terms())
                )
            ]
        return sorted(items, key=lambda item: (-item.count, item.slug))[:limit]

    def possible_synonyms(self, value: str, *, limit: int = 5) -> list[TagUsage]:
        """Find close registered identities before a pending tag is created."""
        query = value.strip().casefold()
        scored: list[tuple[float, TagUsage]] = []
        for item in self.list_tags():
            terms = item.metadata.search_terms() if item.metadata is not None else (item.slug,)
            score = max(SequenceMatcher(None, query, term).ratio() for term in terms)
            if (
                score >= 0.62
                or query in terms
                or any(query in term or term in query for term in terms)
            ):
                scored.append((score, item))
        return [
            item for _, item in sorted(scored, key=lambda pair: (-pair[0], -pair[1].count))[:limit]
        ]

    def cooccurrence(self, *, top_n: int = 20) -> list[TagCooccurrence]:
        """Count unordered tag pairs among the Top-N tags."""
        return self.overview(top_n=top_n).cooccurrences

    def overview(self, *, top_n: int = 20) -> TagOverviewResult:
        """Build frequency, co-occurrence, year, and chapter projections once."""
        if top_n < 1:
            raise DataValidationError("top_n must be at least 1")
        snapshot = self.repository.scan()
        snapshot.require_consistent()
        frequencies = Counter(
            topic for record in snapshot.records for topic in set(record.question.topics)
        )
        selected = {
            slug
            for slug, _ in sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))[:top_n]
        }
        pairs: Counter[tuple[str, str]] = Counter()
        for record in snapshot.records:
            topics = sorted(set(record.question.topics) & selected)
            for index, left in enumerate(topics):
                for right in topics[index + 1 :]:
                    pairs[(left, right)] += 1
        cooccurrences = [
            TagCooccurrence(left=left, right=right, count=count)
            for (left, right), count in sorted(
                pairs.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
            )
        ]
        metadata = self.taxonomy.load().by_slug()
        frequencies_result = [
            TagUsage(
                slug=slug,
                count=frequencies[slug],
                registered=slug in metadata,
                metadata=metadata.get(slug),
            )
            for slug in sorted(selected, key=lambda item: (-frequencies[item], item))
        ]
        year_coverage: Counter[tuple[str, str]] = Counter()
        chapter_coverage: Counter[tuple[str, str]] = Counter()
        for record in snapshot.records:
            record_topics = set(record.question.topics) & selected
            year = record.question.created_at[:4] if record.question.created_at else "未记录"
            chapter = record.question.chapter or "未记录"
            for topic in record_topics:
                year_coverage[(year, topic)] += 1
                chapter_coverage[(chapter, topic)] += 1
        return TagOverviewResult(
            frequencies=frequencies_result,
            cooccurrences=cooccurrences,
            year_coverage=[
                TagCoverageCell(axis=axis, tag=tag, count=count)
                for (axis, tag), count in sorted(year_coverage.items())
            ],
            chapter_coverage=[
                TagCoverageCell(axis=axis, tag=tag, count=count)
                for (axis, tag), count in sorted(chapter_coverage.items())
            ],
        )

    def rename(self, old: str, new: str, *, dry_run: bool, command: str) -> TagMutationResult:
        """Rename a canonical slug everywhere and retain the old slug as an alias."""
        snapshot, registry = self._state()
        old_slug = registry.resolve(old) or old.strip()
        new_slug = normalize_tag_slug(new)
        if old_slug == new_slug:
            raise DataValidationError("old and new tag slugs are identical")
        entries = registry.by_slug()
        if new_slug in entries:
            raise ConflictError(f"target tag already exists; use merge: {new_slug}")
        current = entries.get(old_slug) or TaxonomyTag(slug=old_slug, status=TagStatus.PENDING)
        replacement = current.model_copy(
            update={"slug": new_slug, "aliases": list(dict.fromkeys([*current.aliases, old_slug]))}
        )
        tags = [replacement if tag.slug == old_slug else tag for tag in registry.tags]
        if old_slug not in entries:
            tags.append(replacement)
        return self._replace_topics(
            snapshot,
            registry,
            Taxonomy(tags=sorted(tags, key=lambda tag: tag.slug)),
            {old_slug: new_slug},
            TagMutationMetadata("tag_rename", command, dry_run),
        )

    def merge(self, source: str, target: str, *, dry_run: bool, command: str) -> TagMutationResult:
        """Merge a source tag into a target and preserve source identities as aliases."""
        snapshot, registry = self._state()
        source_slug = registry.resolve(source) or source.strip()
        target_slug = registry.resolve(target) or normalize_tag_slug(target)
        if source_slug == target_slug:
            raise DataValidationError("source and target tags are identical")
        entries = registry.by_slug()
        source_tag = entries.get(source_slug) or TaxonomyTag(
            slug=source_slug, status=TagStatus.PENDING
        )
        target_tag = entries.get(target_slug) or TaxonomyTag(
            slug=target_slug, status=TagStatus.PENDING
        )
        aliases = list(
            dict.fromkeys(
                [
                    *target_tag.aliases,
                    source_slug,
                    *source_tag.aliases,
                    *(value for value in (source_tag.name_zh, source_tag.name_en) if value),
                ]
            )
        )
        merged = target_tag.model_copy(update={"aliases": aliases})
        tags = [tag for tag in registry.tags if tag.slug not in {source_slug, target_slug}]
        tags.append(merged)
        return self._replace_topics(
            snapshot,
            registry,
            Taxonomy(tags=sorted(tags, key=lambda tag: tag.slug)),
            {source_slug: target_slug},
            TagMutationMetadata("tag_merge", command, dry_run),
        )

    def delete(self, value: str, *, dry_run: bool, command: str) -> TagMutationResult:
        """Delete a registry entry and remove its relation from every question."""
        snapshot, registry = self._state()
        slug = registry.resolve(value) or value.strip()
        taxonomy_after = Taxonomy(tags=[tag for tag in registry.tags if tag.slug != slug])
        return self._replace_topics(
            snapshot,
            registry,
            taxonomy_after,
            {slug: None},
            TagMutationMetadata("tag_delete", command, dry_run),
        )

    def normalize(self, *, dry_run: bool, command: str) -> TagMutationResult:
        """Canonicalize aliases and register unknown topic slugs as pending."""
        snapshot, registry = self._state()
        replacements: dict[str, str] = {}
        tags = list(registry.tags)
        known = registry.by_slug()
        for topic in sorted(
            {topic for record in snapshot.records for topic in record.question.topics}
        ):
            resolved = registry.resolve(topic)
            canonical = resolved or normalize_tag_slug(topic)
            replacements[topic] = canonical
            if canonical not in known:
                pending = TaxonomyTag(slug=canonical, status=TagStatus.PENDING)
                tags.append(pending)
                known[canonical] = pending
        return self._replace_topics(
            snapshot,
            registry,
            Taxonomy(tags=sorted(tags, key=lambda tag: tag.slug)),
            replacements,
            TagMutationMetadata("tag_normalize", command, dry_run),
        )

    def bulk_edit(
        self,
        question_ids: Iterable[str],
        *,
        add: Iterable[str] = (),
        remove: Iterable[str] = (),
        dry_run: bool,
        command: str,
    ) -> TagMutationResult:
        """Add or remove tags from selected questions in one transaction."""
        snapshot, registry = self._state()
        selected_ids = tuple(dict.fromkeys(question_ids))
        if not selected_ids:
            raise DataValidationError("at least one question ID is required")
        additions, registry_after = self._canonical_additions(registry, add)
        removals = {registry.resolve(value) or value.strip() for value in remove}
        if set(additions) & removals:
            raise DataValidationError("a tag cannot be added and removed together")
        selected = {snapshot.locate(question_id).question.id for question_id in selected_ids}
        after_by_id = {
            record.question.id: [
                *[topic for topic in record.question.topics if topic not in removals],
                *(topic for topic in additions if topic not in record.question.topics),
            ]
            for record in snapshot.records
            if record.question.id in selected
        }
        return self._commit_plan(
            snapshot,
            registry,
            registry_after,
            after_by_id,
            TagMutationMetadata("tag_bulk_edit", command, dry_run),
        )

    def update_tag(self, tag: TaxonomyTag, *, dry_run: bool, command: str) -> TagMutationResult:
        """Create or update registry metadata without changing question relations."""
        snapshot, registry = self._state()
        tags = [existing for existing in registry.tags if existing.slug != tag.slug]
        tags.append(tag)
        return self._commit_plan(
            snapshot,
            registry,
            Taxonomy(tags=sorted(tags, key=lambda item: item.slug)),
            {},
            TagMutationMetadata("tag_update", command, dry_run),
        )

    def register_pending(
        self, values: Iterable[str], *, dry_run: bool, command: str
    ) -> TagMutationResult:
        """Register previously unseen canonical slugs without changing relations."""
        snapshot, registry = self._state()
        _, registry_after = self._canonical_additions(registry, values)
        return self._commit_plan(
            snapshot,
            registry,
            registry_after,
            {},
            TagMutationMetadata("tag_register_pending", command, dry_run),
        )

    def undo(self, token: str, *, dry_run: bool, command: str) -> TagMutationResult:
        """Reverse one tag mutation from its durable history record."""
        return self.mutations.undo(token, dry_run=dry_run, command=command)

    def _state(self) -> tuple[RepositorySnapshot, Taxonomy]:
        snapshot = self.repository.scan()
        snapshot.require_consistent()
        return snapshot, self.taxonomy.load()

    def _canonical_additions(
        self, registry: Taxonomy, values: Iterable[str]
    ) -> tuple[list[str], Taxonomy]:
        additions: list[str] = []
        tags = list(registry.tags)
        known = registry.by_slug()
        for value in values:
            canonical = registry.resolve(value) or normalize_tag_slug(value)
            if canonical not in additions:
                additions.append(canonical)
            if canonical not in known:
                pending = TaxonomyTag(slug=canonical, status=TagStatus.PENDING)
                tags.append(pending)
                known[canonical] = pending
        return additions, Taxonomy(tags=sorted(tags, key=lambda item: item.slug))

    def _replace_topics(
        self,
        snapshot: RepositorySnapshot,
        before: Taxonomy,
        after: Taxonomy,
        replacements: Mapping[str, str | None],
        metadata: TagMutationMetadata,
    ) -> TagMutationResult:
        after_by_id: dict[str, list[str]] = {}
        for record in snapshot.records:
            topics: list[str] = []
            for topic in record.question.topics:
                replacement = replacements.get(topic, topic)
                if replacement is not None and replacement not in topics:
                    topics.append(replacement)
            if topics != record.question.topics:
                after_by_id[record.question.id] = topics
        return self._commit_plan(
            snapshot,
            before,
            after,
            after_by_id,
            metadata,
        )

    def _commit_plan(
        self,
        snapshot: RepositorySnapshot,
        before: Taxonomy,
        after: Taxonomy,
        after_by_id: dict[str, list[str]],
        metadata: TagMutationMetadata,
    ) -> TagMutationResult:
        questions: list[Question] = []
        changes: list[TagQuestionChange] = []
        for record in snapshot.records:
            topics = after_by_id.get(record.question.id)
            if topics is None or topics == record.question.topics:
                continue
            if not topics:
                raise DataValidationError(
                    f"tag operation would leave {record.question.id} without topics"
                )
            values = record.question.model_dump()
            values["topics"] = topics
            candidate = Question.model_validate(values)
            questions.append(candidate)
            changes.append(
                TagQuestionChange(
                    id=candidate.id,
                    before=record.question.topics,
                    after=candidate.topics,
                )
            )
        plan = TagMutationPlan(
            snapshot=snapshot,
            taxonomy_before=before,
            taxonomy_after=after,
            questions=tuple(questions),
            changes=tuple(changes),
            operation=metadata.operation,
            command=metadata.command,
            dry_run=metadata.dry_run,
        )
        return self.mutations.commit(plan)
