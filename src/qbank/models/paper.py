"""Paper selection and rendering-option models."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from qbank.models.common import SchemaVersion, StrictModel
from qbank.models.question import ID_PATTERN


class PaperQuestion(StrictModel):
    """One scored paper question reference."""

    id: str = Field(pattern=ID_PATTERN)
    score: float = Field(gt=0)


class PaperSection(StrictModel):
    """A titled paper section."""

    title: str = Field(min_length=1)
    instructions: str = ""
    questions: list[PaperQuestion] = Field(min_length=1)


class PaperMetadata(StrictModel):
    """Paper-level metadata."""

    author: str | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
    total_score: float | None = Field(default=None, gt=0)


class PaperOptions(StrictModel):
    """Paper rendering defaults."""

    show_scores: bool = True
    show_question_ids: bool = False
    include_answers: bool = False
    include_solutions: bool = False
    include_rubric: bool = False


class Paper(StrictModel):
    """paper.yaml structure."""

    schema_version: SchemaVersion
    title: str = Field(min_length=1)
    subtitle: str = ""
    language: str = "zh-CN"
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    metadata: PaperMetadata = Field(default_factory=PaperMetadata)
    sections: list[PaperSection] = Field(min_length=1)
    options: PaperOptions = Field(default_factory=PaperOptions)

    @field_validator("date")
    @classmethod
    def date_is_iso_calendar_date(cls, value: str | None) -> str | None:
        """Validate YYYY-MM-DD paper dates."""
        if value is None:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must use YYYY-MM-DD") from exc
        if parsed.isoformat() != value:
            raise ValueError("date must use YYYY-MM-DD")
        return value

    @property
    def calculated_total(self) -> float:
        """Return the sum of all question scores."""
        return sum(item.score for section in self.sections for item in section.questions)


class PaperBuildOptions(StrictModel):
    """Resolved command-line overrides for a paper build."""

    with_answers: bool | None = None
    with_solutions: bool | None = None
    with_rubric: bool | None = None
    show_ids: bool | None = None
    allow_deprecated: bool = False


class PaperBuildRequest(StrictModel):
    """Output target and rendering options for one paper build."""

    output_format: Literal["md", "html", "docx"]
    output: Path | None = None
    options: PaperBuildOptions = Field(default_factory=PaperBuildOptions)
