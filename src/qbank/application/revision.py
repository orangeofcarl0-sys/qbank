"""Deterministic optimistic-concurrency revision for authoritative project data."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from qbank.context import ProjectContext
from qbank.errors import DataValidationError


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
    digest = hashlib.sha256()
    files = _fixed_files(context.root, fixed)
    files.extend(_contained_files(context.root, roots))
    for path in sorted(set(files), key=lambda item: item.relative_to(context.root).as_posix()):
        relative = path.relative_to(context.root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def _fixed_files(root: Path, candidates: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in candidates:
        if path.is_symlink():
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
            if candidate.is_symlink():
                raise DataValidationError(
                    f"symbolic links are not supported in authoritative MCP data: {candidate}"
                )
            if candidate.is_file():
                files.append(candidate)
    return files
