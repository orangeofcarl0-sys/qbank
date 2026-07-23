"""Deterministic optimistic-concurrency revision for authoritative project data."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from qbank.context import ProjectContext
from qbank.domain import RepositorySnapshot
from qbank.errors import DataValidationError
from qbank.markdown_codec import render_question
from qbank.models import Question
from qbank.utils import is_reparse_point


def repository_revision(context: ProjectContext) -> str:
    """Hash configured authoritative inputs without reading generated state."""
    roots = (
        context.paths.questions,
        context.paths.assets,
        context.paths.papers,
    )
    fixed = (
        context.root / "qbank.yaml",
        context.root / "taxonomy.yaml",
        context.root / "views.yaml",
    )
    files = _fixed_files(context.root, fixed)
    files.extend(_contained_files(context.root, roots))
    return _content_revision(context.root, {path: path.read_bytes() for path in files})


def question_projection_revision(context: ProjectContext) -> str:
    """Hash question sources without parsing Markdown or trusting file metadata."""
    files = _contained_files(context.root, (context.paths.questions,))
    try:
        markdown = {
            path: path.read_text(encoding="utf-8").encode("utf-8")
            for path in files
            if path.suffix.casefold() == ".md"
        }
    except (OSError, UnicodeError) as exc:
        raise DataValidationError(f"unable to hash question sources: {exc}") from exc
    return _content_revision(context.root, markdown)


def planned_question_projection_revision(
    context: ProjectContext,
    snapshot: RepositorySnapshot,
    *,
    questions: Sequence[Question] = (),
    deleted_ids: Sequence[str] = (),
) -> str:
    """Hash the deterministic post-commit question projection from an existing snapshot."""
    removed = set(deleted_ids) | {question.id for question in questions}
    contents: dict[Path, bytes] = {
        record.path: record.text.encode("utf-8")
        for record in snapshot.records
        if record.question.id not in removed
    }
    for question in questions:
        destination = context.paths.questions / question.subject / f"{question.id}.md"
        contents[destination] = render_question(question).encode("utf-8")
    return _content_revision(context.root, contents)


def _content_revision(root: Path, contents: Mapping[Path, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(contents, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = contents[path]
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _fixed_files(root: Path, candidates: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in candidates:
        if is_reparse_point(path):
            raise DataValidationError(f"symbolic authoritative file is not supported: {path}")
        if path.is_file():
            try:
                path.resolve().relative_to(root.resolve())
            except ValueError as exc:
                raise DataValidationError(
                    f"authoritative path escapes the repository: {path}"
                ) from exc
            files.append(path)
    return files


def _contained_files(root: Path, directories: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    resolved_root = root.resolve()
    for directory in directories:
        if not directory.exists():
            continue
        for candidate in directory.rglob("*"):
            resolved = candidate.resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError as exc:
                raise DataValidationError(
                    f"authoritative path escapes the repository: {candidate}"
                ) from exc
            if is_reparse_point(candidate):
                raise DataValidationError(
                    f"reparse points are not supported in authoritative data: {candidate}"
                )
            if candidate.is_file():
                files.append(candidate)
    return files
