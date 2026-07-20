"""Validated question-query inputs."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from qbank.models.common import StrictModel
from qbank.models.question import QuestionStatus, QuestionType


class QueryFilters(StrictModel):
    """Validated source-query filters shared by query and export."""

    subject: str | None = None
    chapter: str | None = None
    topics: list[str] = Field(default_factory=list)
    topic_mode: Literal["and", "or"] = "and"
    question_type: QuestionType | None = None
    status: QuestionStatus | None = None
    difficulty_min: int | None = Field(default=None, ge=1, le=5)
    difficulty_max: int | None = Field(default=None, ge=1, le=5)
    language: str | None = None
    limit: int = Field(default=100, ge=1)
    offset: int = Field(default=0, ge=0)

    @field_validator("topics")
    @classmethod
    def query_topics_are_nonempty(cls, value: list[str]) -> list[str]:
        """Normalize repeated topic filters."""
        if any(not item.strip() for item in value):
            raise ValueError("topic filters must not be empty")
        return list(dict.fromkeys(item.strip() for item in value))

    @model_validator(mode="after")
    def difficulty_range_is_ordered(self) -> QueryFilters:
        """Reject inverted difficulty ranges."""
        if (
            self.difficulty_min is not None
            and self.difficulty_max is not None
            and self.difficulty_min > self.difficulty_max
        ):
            raise ValueError("difficulty_min must not exceed difficulty_max")
        return self


class IngestOptions(StrictModel):
    """Batch import behavior independent of transport parsing."""

    upsert: bool = False
    dry_run: bool = False
    continue_on_error: bool = False
    command: str = "qbank ingest"
