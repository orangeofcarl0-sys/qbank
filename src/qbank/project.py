"""Project initialization, discovery, and compatibility path helpers."""

from __future__ import annotations

from pathlib import Path

from qbank.bootstrap import create_question_service
from qbank.context import (
    ProjectContext,
    resolve_project_path,
)
from qbank.context import (
    find_project_root as _find_project_root,
)
from qbank.errors import ConflictError, DataValidationError
from qbank.init_resources import (
    initialization_resources,
    packaged_init_text,
)
from qbank.models import ProjectConfig
from qbank.utils import atomic_write_text

# Compatibility constants are loaded from the canonical package resources.
DEFAULT_CONFIG = packaged_init_text("qbank.yaml")
DEFAULT_MD_TEMPLATE = packaged_init_text("templates/paper.md.j2")
DEFAULT_HTML_TEMPLATE = packaged_init_text("templates/paper.html.j2")
DEMO_PAPER = packaged_init_text("papers/demo-paper.yaml")
DEMO_SVG = packaged_init_text("assets/images/interference.svg")


def find_project_root(start: Path | None = None) -> Path:
    """Search upward for qbank.yaml."""
    return _find_project_root(start)


def load_config(root: Path) -> ProjectConfig:
    """Load and validate qbank.yaml."""
    return ProjectContext.from_root(root).config


def path_for(root: Path, config: ProjectConfig, name: str) -> Path:
    """Resolve one configured project path."""
    if name not in type(config.paths).model_fields:
        raise DataValidationError(f"unknown configured path: {name}")
    return resolve_project_path(
        root,
        getattr(config.paths, name),
        label=f"configured path '{name}'",
    )


def initialize_project(target: Path, *, force: bool = False) -> Path:
    """Create a usable qbank project after a complete conflict preflight."""
    target = target.resolve()
    materialized = tuple(
        (
            target.joinpath(*resource.destination.parts),
            resource.text(),
        )
        for resource in initialization_resources()
    )
    index = target / ".qbank/index.sqlite"
    conflicts = [path for path in (*[path for path, _ in materialized], index) if path.exists()]
    if conflicts and not force:
        relative = ", ".join(path.relative_to(target).as_posix() for path in conflicts)
        raise ConflictError(f"managed file conflict(s): {relative}")
    for directory in (
        "questions/optics",
        "questions/mathematics",
        "questions/electronics",
        "questions/uncategorized",
        "assets/images",
        "assets/diagrams",
        "papers",
        "papers/generated",
        "templates",
        "exports",
        "build",
        "build/ai",
        "schemas",
        ".agents/skills/qbank/agents",
        ".agents/skills/qbank/references",
        ".qbank/history",
    ):
        (target / directory).mkdir(parents=True, exist_ok=True)
    for path, text in materialized:
        atomic_write_text(path, text)
    context = ProjectContext.from_root(target)
    create_question_service(context).rebuild_index()
    return target
