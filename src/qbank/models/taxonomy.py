"""Tag taxonomy, saved-view, and tag-analysis models."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from qbank.models.common import SchemaVersion, StrictModel
from qbank.models.query import QueryFilters

TAG_SLUG_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class TagStatus(StrEnum):
    """Lifecycle state of one registered tag."""

    ACTIVE = "active"
    PENDING = "pending"
    DEPRECATED = "deprecated"


class TaxonomyTag(StrictModel):
    """Display metadata for one canonical topic slug."""

    slug: str = Field(pattern=TAG_SLUG_PATTERN)
    name_zh: str | None = None
    name_en: str | None = None
    aliases: list[str] = Field(default_factory=list)
    color: str | None = Field(default=None, pattern=COLOR_PATTERN)
    description: str | None = None
    parent: str | None = Field(default=None, pattern=TAG_SLUG_PATTERN)
    status: TagStatus = TagStatus.ACTIVE

    @field_validator("name_zh", "name_en", "description")
    @classmethod
    def optional_text_is_trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("aliases")
    @classmethod
    def aliases_are_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("tag aliases must not be empty")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def references_are_not_self_aliases(self) -> TaxonomyTag:
        folded = self.slug.casefold()
        if self.parent == self.slug:
            raise ValueError("a tag cannot be its own parent")
        if any(alias.casefold() == folded for alias in self.aliases):
            raise ValueError("a canonical slug must not also be its own alias")
        return self

    def search_terms(self) -> tuple[str, ...]:
        """Return normalized terms used by Studio autocomplete."""
        values = (self.slug, self.name_zh, self.name_en, *self.aliases)
        return tuple(value.casefold() for value in values if value)


def _taxonomy_tags() -> list[TaxonomyTag]:
    return []


class Taxonomy(StrictModel):
    """Project-level tag metadata; question relations remain in Markdown."""

    schema_version: SchemaVersion = "1.0"
    tags: list[TaxonomyTag] = Field(default_factory=_taxonomy_tags)

    @model_validator(mode="after")
    def identities_are_unambiguous(self) -> Taxonomy:
        slugs = [tag.slug for tag in self.tags]
        if len(slugs) != len(set(slugs)):
            raise ValueError("taxonomy tag slugs must be unique")
        identities: dict[str, str] = {}
        for tag in self.tags:
            for value in (tag.slug, tag.name_zh, tag.name_en, *tag.aliases):
                if not value:
                    continue
                folded = value.casefold()
                previous = identities.get(folded)
                if previous is not None and previous != tag.slug:
                    raise ValueError(
                        f"taxonomy identity {value!r} is ambiguous between {previous} and {tag.slug}"
                    )
                identities[folded] = tag.slug
        known = set(slugs)
        missing_parents = sorted(
            {tag.parent for tag in self.tags if tag.parent is not None and tag.parent not in known}
        )
        if missing_parents:
            raise ValueError(f"unknown taxonomy parent(s): {', '.join(missing_parents)}")
        return self

    def by_slug(self) -> dict[str, TaxonomyTag]:
        """Return canonical entries keyed by slug."""
        return {tag.slug: tag for tag in self.tags}

    def resolve(self, value: str) -> str | None:
        """Resolve a slug, display name, or alias to its canonical slug."""
        folded = value.strip().casefold()
        for tag in self.tags:
            if folded in tag.search_terms():
                return tag.slug
        return None


class SavedViewKind(StrEnum):
    """Additional predicates used by built-in Studio views."""

    FILTER = "filter"
    NEEDS_REDRAW = "needs_redraw"
    CURRENT_PAPER = "current_paper"


class SavedView(StrictModel):
    """A named, persistent question-list query."""

    name: str = Field(min_length=1)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    kind: SavedViewKind = SavedViewKind.FILTER
    protected: bool = False

    @field_validator("name")
    @classmethod
    def name_is_not_whitespace(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("saved view name must not be empty")
        return normalized


def _saved_views() -> list[SavedView]:
    return []


class SavedViewRegistry(StrictModel):
    """Persistent user-created views; built-ins are supplied by the service."""

    schema_version: SchemaVersion = "1.0"
    views: list[SavedView] = Field(default_factory=_saved_views)

    @model_validator(mode="after")
    def names_are_unique(self) -> SavedViewRegistry:
        folded = [view.name.casefold() for view in self.views]
        if len(folded) != len(set(folded)):
            raise ValueError("saved view names must be unique")
        if any(view.protected for view in self.views):
            raise ValueError("protected views are built in and must not be stored")
        return self


def normalize_tag_slug(value: str) -> str:
    """Convert a user label to a conservative canonical slug."""
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.strip().casefold()).strip("-._")
    if not normalized or re.fullmatch(TAG_SLUG_PATTERN, normalized) is None:
        raise ValueError(f"cannot derive a canonical tag slug from {value!r}")
    return normalized
