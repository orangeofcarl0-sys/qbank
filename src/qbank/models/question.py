"""Question, patch, and provenance domain models."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from qbank.models.common import SchemaVersion, StrictModel
from qbank.question_layout import QUESTION_CONTENT_FIELDS as ORDERED_CONTENT_FIELDS
from qbank.question_layout import QUESTION_SECTIONS

ID_PATTERN = r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$"
SUBJECT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"


class QuestionType(StrEnum):
    """Supported question types."""

    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    SHORT_ANSWER = "short_answer"
    PROOF = "proof"
    ESSAY = "essay"
    COMPOSITE = "composite"
    OTHER = "other"


class QuestionStatus(StrEnum):
    """Supported review states."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"


class Source(StrictModel):
    """Short provenance metadata."""

    type: str = Field(min_length=1)
    reference: str | None = None


class Question(StrictModel):
    """Complete AI exchange representation of one question."""

    schema_version: SchemaVersion
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1)
    type: QuestionType
    subject: str = Field(pattern=SUBJECT_PATTERN)
    chapter: str | None = None
    topics: list[str] = Field(min_length=1)
    difficulty: int = Field(ge=1, le=5)
    status: QuestionStatus
    language: str = Field(min_length=1)
    source: Source
    assets: list[str]
    created_at: str | None = Field(default=None, json_schema_extra={"format": "date-time"})
    updated_at: str | None = Field(default=None, json_schema_extra={"format": "date-time"})
    stem_md: str
    options_md: str = ""
    answer_md: str = ""
    solution_md: str = ""
    rubric_md: str = ""
    review_notes_md: str = ""

    @field_validator(*ORDERED_CONTENT_FIELDS)
    @classmethod
    def content_is_canonical_markdown(cls, value: str) -> str:
        """Normalize field boundaries and reject ambiguous canonical headings."""
        normalized = value.strip()
        titles = "|".join(re.escape(section.title) for section in QUESTION_SECTIONS)
        if re.search(rf"(?m)^##[ \t]+(?:{titles})[ \t]*$", normalized):
            raise ValueError("content must not contain a reserved qbank section heading")
        return normalized

    @field_validator("topics")
    @classmethod
    def topics_are_nonempty_strings(cls, value: list[str]) -> list[str]:
        """Reject empty or whitespace-only topic values."""
        if any(not item.strip() for item in value):
            raise ValueError("topics must contain only non-empty strings")
        return list(dict.fromkeys(item.strip() for item in value))

    @field_validator("title", "language")
    @classmethod
    def required_text_is_not_whitespace(cls, value: str) -> str:
        """Normalize short required text and reject whitespace-only values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("stem_md")
    @classmethod
    def stem_is_not_whitespace(cls, value: str) -> str:
        """Require a non-empty question stem."""
        if not value.strip():
            raise ValueError("stem_md must not be empty")
        return value

    @field_validator("assets")
    @classmethod
    def assets_are_relative_strings(cls, value: list[str]) -> list[str]:
        """Reject empty asset references; containment is checked per project."""
        if any(not item.strip() for item in value):
            raise ValueError("assets must contain only non-empty strings")
        return list(dict.fromkeys(item.replace("\\", "/").strip() for item in value))

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def timestamps_are_utc_iso8601(cls, value: Any) -> str | None:
        """Validate and normalize optional timestamps to UTC with a Z suffix."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO 8601 string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be valid ISO 8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


QUESTION_CONTENT_FIELDS = ORDERED_CONTENT_FIELDS
QUESTION_METADATA_FIELDS = tuple(
    name for name in Question.model_fields if name not in QUESTION_CONTENT_FIELDS
)
QUESTION_IMMUTABLE_FIELDS = {"id", "schema_version", "created_at", "updated_at"}
QUESTION_PATCHABLE_FIELDS = set(Question.model_fields) - QUESTION_IMMUTABLE_FIELDS - {"topics"}


def _inline_schema(node: Any, definitions: dict[str, Any]) -> Any:
    """Inline local references so patch field schemas remain self-contained."""
    if isinstance(node, list):
        return [_inline_schema(item, definitions) for item in cast(list[Any], node)]
    if not isinstance(node, dict):
        return node
    mapping = cast(dict[str, Any], node)
    reference = mapping.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        name = reference.rsplit("/", maxsplit=1)[-1]
        return _inline_schema(definitions[name], definitions)
    return {
        key: _inline_schema(value, definitions) for key, value in mapping.items() if key != "$defs"
    }


def _patch_set_json_schema() -> dict[str, Any]:
    question_schema = Question.model_json_schema()
    definitions = cast(dict[str, Any], question_schema.get("$defs", {}))
    properties = cast(dict[str, Any], question_schema["properties"])
    return {
        "type": "object",
        "properties": {
            name: _inline_schema(properties[name], definitions)
            for name in Question.model_fields
            if name in QUESTION_PATCHABLE_FIELDS
        },
        "additionalProperties": False,
    }


class QuestionPatch(StrictModel):
    """Structured question patch."""

    set: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra=_patch_set_json_schema(),
    )
    add_topics: list[str] = Field(default_factory=list)
    remove_topics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_patch_fields(self) -> QuestionPatch:
        """Restrict patch fields and topic values."""
        unknown = sorted(set(self.set) - QUESTION_PATCHABLE_FIELDS)
        if unknown:
            raise ValueError(f"unknown or immutable patch fields: {', '.join(unknown)}")
        for name, value in self.set.items():
            try:
                TypeAdapter(Question.model_fields[name].rebuild_annotation()).validate_python(value)
            except ValidationError as exc:
                message = exc.errors()[0]["msg"]
                raise ValueError(f"invalid patch value for {name}: {message}") from exc
        for topic in [*self.add_topics, *self.remove_topics]:
            if not topic.strip():
                raise ValueError("topic changes must contain non-empty strings")
        overlap = set(self.add_topics) & set(self.remove_topics)
        if overlap:
            raise ValueError(f"topics cannot be added and removed together: {sorted(overlap)}")
        return self


def extract_option_labels(options_md: str) -> set[str]:
    """Extract common Markdown choice labels such as A, B, C, and D."""
    pattern = re.compile(r"(?im)^\s*(?:[-*]\s*)?([A-Z])(?:[.)、：]|\s+-)\s*")
    return {match.group(1) for match in pattern.finditer(options_md)}
