"""Single-pass snapshots of authoritative Markdown question sources."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import cast

from qbank.context import ProjectContext
from qbank.domain import InvalidQuestionSource, QuestionRecord, RepositorySnapshot
from qbank.errors import DataValidationError
from qbank.markdown_codec import parse_question_text, split_frontmatter
from qbank.models import Question
from qbank.yaml_io import load_yaml


class MarkdownQuestionRepository:
    """Filesystem implementation of the authoritative question repository."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def source_paths(self) -> tuple[Path, ...]:
        """Return all Markdown paths without parsing them."""
        return tuple(
            sorted(
                (path for path in self.context.paths.questions.rglob("*.md") if path.is_file()),
                key=lambda path: str(path),
            )
        )

    def scan(self, paths: tuple[Path, ...] | None = None) -> RepositorySnapshot:
        """Read and parse every selected source exactly once."""
        records: list[QuestionRecord] = []
        invalid_sources: list[InvalidQuestionSource] = []
        for path in paths if paths is not None else self.source_paths():
            relative = path.relative_to(self.context.root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
                question, duplicates, metadata = parse_question_text(text)
            except (OSError, UnicodeError, DataValidationError) as exc:
                invalid_sources.append(
                    InvalidQuestionSource(
                        path=path,
                        relative_path=relative,
                        error=str(exc),
                        filename_id=path.stem,
                        frontmatter_id=_frontmatter_id(path),
                    )
                )
                continue
            records.append(
                QuestionRecord(
                    path=path,
                    relative_path=relative,
                    text=text,
                    question=question,
                    duplicate_sections=tuple(duplicates),
                    metadata=metadata,
                )
            )
        counts = Counter(record.question.id for record in records)
        duplicates = frozenset(question_id for question_id, count in counts.items() if count > 1)
        return RepositorySnapshot(
            records=tuple(records),
            invalid_sources=tuple(invalid_sources),
            duplicate_ids=duplicates,
        )

    def destination(self, question: Question) -> Path:
        """Return the canonical source destination for a question."""
        return self.context.paths.questions / question.subject / f"{question.id}.md"


def _frontmatter_id(path: Path) -> str | None:
    try:
        yaml_text, _ = split_frontmatter(path.read_text(encoding="utf-8"))
        raw = load_yaml(yaml_text)
    except (OSError, UnicodeError, DataValidationError, ValueError):
        return None
    mapping = cast(dict[str, object], raw) if isinstance(raw, dict) else {}
    value = mapping.get("id")
    return value if isinstance(value, str) else None
