"""Canonical Markdown/front-matter layout for question sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuestionSection:
    """One canonical level-two Markdown section."""

    title: str
    field: str


QUESTION_SECTIONS = (
    QuestionSection("题目", "stem_md"),
    QuestionSection("选项", "options_md"),
    QuestionSection("答案", "answer_md"),
    QuestionSection("解析", "solution_md"),
    QuestionSection("评分要点", "rubric_md"),
    QuestionSection("审阅备注", "review_notes_md"),
)

QUESTION_CONTENT_FIELDS = tuple(section.field for section in QUESTION_SECTIONS)
SECTION_TO_FIELD = {section.title: section.field for section in QUESTION_SECTIONS}
FIELD_TO_SECTION = {section.field: section.title for section in QUESTION_SECTIONS}
