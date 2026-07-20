"""Resolved, immutable project configuration shared by application services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qbank.errors import DataValidationError, ProjectNotFoundError
from qbank.models import ProjectConfig
from qbank.yaml_io import load_yaml


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Absolute paths derived from one validated project configuration."""

    questions: Path
    assets: Path
    papers: Path
    templates: Path
    exports: Path
    build: Path
    state: Path
    reference_docx: Path

    def configured(self) -> dict[str, Path]:
        """Return configured directory paths keyed by their public names."""
        return {
            "questions": self.questions,
            "assets": self.assets,
            "papers": self.papers,
            "templates": self.templates,
            "exports": self.exports,
            "build": self.build,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class ProjectContext:
    """A project root, validated configuration, and resolved path set."""

    root: Path
    config: ProjectConfig
    paths: ProjectPaths

    @classmethod
    def discover(cls, start: Path | None = None) -> ProjectContext:
        """Find a project root upward from *start* and load it."""
        return cls.from_root(find_project_root(start))

    @classmethod
    def from_root(cls, root: Path) -> ProjectContext:
        """Load and fully resolve a project rooted at *root*."""
        resolved_root = root.resolve()
        config_path = resolved_root / "qbank.yaml"
        try:
            raw = load_yaml(config_path.read_text(encoding="utf-8"))
            config = ProjectConfig.model_validate(raw)
        except (OSError, UnicodeError, ValueError) as exc:
            raise DataValidationError(f"invalid qbank.yaml: {exc}") from exc
        return cls.from_config(resolved_root, config)

    @classmethod
    def from_config(cls, root: Path, config: ProjectConfig) -> ProjectContext:
        """Resolve an already validated configuration for compatibility adapters."""
        resolved_root = root.resolve()
        directories = {
            name: resolve_project_path(
                resolved_root,
                getattr(config.paths, name),
                label=f"configured path '{name}'",
            )
            for name in type(config.paths).model_fields
        }
        _ensure_disjoint(directories)
        reference_docx = resolve_project_path(
            resolved_root,
            config.export.reference_docx,
            label="configured reference_docx",
        )
        return cls(
            root=resolved_root,
            config=config,
            paths=ProjectPaths(
                questions=directories["questions"],
                assets=directories["assets"],
                papers=directories["papers"],
                templates=directories["templates"],
                exports=directories["exports"],
                build=directories["build"],
                state=directories["state"],
                reference_docx=reference_docx,
            ),
        )

    def path(self, name: str) -> Path:
        """Return one configured directory by public configuration name."""
        try:
            return self.paths.configured()[name]
        except KeyError as exc:
            raise DataValidationError(f"unknown configured path: {name}") from exc


def find_project_root(start: Path | None = None) -> Path:
    """Search upward for qbank.yaml without accessing any generated state."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "qbank.yaml").is_file():
            return candidate
    raise ProjectNotFoundError("qbank.yaml not found; run 'qbank init' first")


def resolve_project_path(root: Path, relative: str, *, label: str) -> Path:
    """Resolve a configured path and reject symlink or traversal escape."""
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise DataValidationError(f"{label} escapes the project root: {candidate}") from exc
    return candidate


def _ensure_disjoint(paths: dict[str, Path]) -> None:
    items = list(paths.items())
    for index, (left_name, left) in enumerate(items):
        for right_name, right in items[index + 1 :]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise DataValidationError(
                    "configured paths resolve to overlapping locations: "
                    f"{left_name} and {right_name}"
                )
