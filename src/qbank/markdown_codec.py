"""Canonical parsing and rendering for authoritative question Markdown."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError
from ruamel.yaml.error import YAMLError

from qbank.errors import MarkdownParseError
from qbank.models import QUESTION_METADATA_FIELDS, Question
from qbank.question_layout import (
    QUESTION_CONTENT_FIELDS,
    QUESTION_SECTIONS,
    SECTION_TO_FIELD,
)
from qbank.yaml_io import dump_yaml, load_yaml

SECTION_PATTERN = re.compile(r"(?m)^##[ \t]+(.+?)[ \t]*$")


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split YAML front matter and Markdown body."""
    normalized = text.lstrip("\ufeff")
    if not normalized.startswith("---"):
        raise MarkdownParseError("question file must start with YAML front matter")
    lines = normalized.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise MarkdownParseError("invalid YAML front matter opening delimiter")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise MarkdownParseError("missing YAML front matter closing delimiter")


def parse_sections(body: str) -> tuple[dict[str, str], list[str]]:
    """Parse supported level-two sections and report duplicate names."""
    matches = list(SECTION_PATTERN.finditer(body))
    values = {field: "" for field in QUESTION_CONTENT_FIELDS}
    duplicates: list[str] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        section_name = match.group(1).strip()
        if section_name not in SECTION_TO_FIELD:
            continue
        if section_name in seen:
            duplicates.append(section_name)
        seen.add(section_name)
        content_start = match.end()
        content_end = len(body)
        for later in matches[index + 1 :]:
            if later.group(1).strip() in SECTION_TO_FIELD:
                content_end = later.start()
                break
        values[SECTION_TO_FIELD[section_name]] = body[content_start:content_end].strip()
    return values, duplicates


def parse_question_text(text: str) -> tuple[Question, list[str], dict[str, Any]]:
    """Parse one Markdown question into the exchange model."""
    yaml_text, body = split_frontmatter(text)
    try:
        metadata = load_yaml(yaml_text)
    except YAMLError as exc:
        raise MarkdownParseError(f"invalid YAML front matter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise MarkdownParseError("YAML front matter must be a mapping")
    content, duplicates = parse_sections(body)
    typed_metadata = cast(dict[str, Any], metadata)
    combined = {**typed_metadata, **content}
    try:
        question = Question.model_validate(combined)
    except ValidationError as exc:
        raise MarkdownParseError(str(exc)) from exc
    return question, duplicates, typed_metadata


def parse_question_file(path: Path) -> tuple[Question, list[str], dict[str, Any]]:
    """Read and parse one UTF-8 Markdown question."""
    try:
        return parse_question_text(path.read_text(encoding="utf-8"))
    except MarkdownParseError:
        raise
    except (OSError, UnicodeError) as exc:
        raise MarkdownParseError(f"cannot read question source: {exc}") from exc


def render_question(question: Question) -> str:
    """Serialize a question in stable front-matter and section order."""
    raw = question.model_dump(mode="json")
    metadata: dict[str, Any] = {}
    for name in QUESTION_METADATA_FIELDS:
        value = raw.get(name)
        if name == "chapter" and value is None:
            continue
        if name in {"created_at", "updated_at"} and value is None:
            continue
        metadata[name] = value
    chunks = [f"---\n{dump_yaml(metadata)}\n---\n"]
    for section in QUESTION_SECTIONS:
        value = getattr(question, section.field)
        chunks.append(f"\n## {section.title}\n\n{value.strip()}\n")
    return "".join(chunks).rstrip() + "\n"
