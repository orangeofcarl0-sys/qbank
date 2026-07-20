"""Markdown serialization and question repository operations."""

from __future__ import annotations

from pathlib import Path

from qbank.application.exchange import (
    JsonLineRecord as JsonLineRecord,
)
from qbank.application.exchange import (
    load_json_records as load_json_records,
)
from qbank.application.exchange import (
    parse_json_lines as parse_json_lines,
)
from qbank.context import ProjectContext
from qbank.errors import MarkdownParseError as MarkdownParseError
from qbank.markdown_codec import (
    SECTION_PATTERN as SECTION_PATTERN,
)
from qbank.markdown_codec import (
    parse_question_file as parse_question_file,
)
from qbank.markdown_codec import (
    parse_question_text as parse_question_text,
)
from qbank.markdown_codec import (
    parse_sections as parse_sections,
)
from qbank.markdown_codec import (
    render_question as render_question,
)
from qbank.markdown_codec import (
    split_frontmatter as split_frontmatter,
)
from qbank.models import ProjectConfig, Question
from qbank.question_layout import (
    SECTION_TO_FIELD as CANONICAL_SECTION_TO_FIELD,
)
from qbank.repository import MarkdownQuestionRepository
from qbank.utils import utc_now

SECTION_TO_FIELD = CANONICAL_SECTION_TO_FIELD


def question_files(root: Path, config: ProjectConfig) -> list[Path]:
    """Compatibility adapter returning repository source paths."""
    context = ProjectContext.from_config(root, config)
    return list(MarkdownQuestionRepository(context).source_paths())


def locate_question(root: Path, config: ProjectConfig, question_id: str) -> tuple[Path, Question]:
    """Locate through the single-pass repository snapshot."""
    context = ProjectContext.from_config(root, config)
    record = MarkdownQuestionRepository(context).scan().locate(question_id)
    return record.path, record.question


def source_paths_for_id(root: Path, config: ProjectConfig, question_id: str) -> list[Path]:
    """Find identity hints through the single-pass repository snapshot."""
    context = ProjectContext.from_config(root, config)
    snapshot = MarkdownQuestionRepository(context).scan()
    return list(snapshot.source_paths_for_id(question_id))


def read_all_questions(root: Path, config: ProjectConfig) -> list[tuple[Path, Question]]:
    """Read all questions through one consistent repository snapshot."""
    context = ProjectContext.from_config(root, config)
    snapshot = MarkdownQuestionRepository(context).scan()
    snapshot.require_consistent()
    return [(record.path, record.question) for record in snapshot.records]


def question_destination(root: Path, config: ProjectConfig, question: Question) -> Path:
    """Return the repository's canonical destination."""
    context = ProjectContext.from_config(root, config)
    return MarkdownQuestionRepository(context).destination(question)


def prepare_question_for_write(question: Question, *, previous: Question | None = None) -> Question:
    """Fill and update timestamps for a pending write."""
    now = utc_now()
    values = question.model_dump()
    values["created_at"] = (
        previous.created_at if previous and previous.created_at else question.created_at or now
    )
    values["updated_at"] = now
    return Question.model_validate(values)
