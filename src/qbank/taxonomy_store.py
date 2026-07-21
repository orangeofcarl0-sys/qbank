"""YAML persistence for tag metadata and saved question views."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.models import SavedViewRegistry, Taxonomy
from qbank.utils import atomic_write_text
from qbank.yaml_io import dump_yaml, load_yaml


class YamlTaxonomyStore:
    """Project-level taxonomy.yaml adapter."""

    def __init__(self, context: ProjectContext):
        self.context = context

    @property
    def path(self) -> Path:
        return self.context.root / "taxonomy.yaml"

    def load(self) -> Taxonomy:
        """Read the registry without creating missing state."""
        if not self.path.is_file():
            return Taxonomy()
        try:
            return Taxonomy.model_validate(load_yaml(self.path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            raise DataValidationError(f"invalid taxonomy.yaml: {exc}") from exc

    def text(self, taxonomy: Taxonomy) -> str:
        """Serialize a registry deterministically."""
        return dump_yaml(taxonomy.model_dump(mode="json", exclude_none=True)) + "\n"


class YamlSavedViewStore:
    """Versionable root-level saved-view definitions."""

    def __init__(self, context: ProjectContext):
        self.context = context

    @property
    def path(self) -> Path:
        return self.context.root / "views.yaml"

    def load(self) -> SavedViewRegistry:
        """Read custom views without creating files from a read operation."""
        if not self.path.is_file():
            return SavedViewRegistry()
        try:
            return SavedViewRegistry.model_validate(
                load_yaml(self.path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeError, ValueError, ValidationError) as exc:
            raise DataValidationError(f"invalid views.yaml: {exc}") from exc

    def save(self, registry: SavedViewRegistry) -> None:
        """Atomically replace custom view definitions."""
        atomic_write_text(
            self.path,
            dump_yaml(registry.model_dump(mode="json", exclude_none=True)) + "\n",
        )
