"""Project configuration models."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from pydantic import Field, field_validator, model_validator

from qbank.models.common import SchemaVersion, StrictModel
from qbank.models.question import QuestionStatus


class PathsConfig(StrictModel):
    """Project-relative paths."""

    questions: str = "questions"
    assets: str = "assets"
    papers: str = "papers"
    templates: str = "templates"
    exports: str = "exports"
    build: str = "build"
    state: str = ".qbank"

    @field_validator("*")
    @classmethod
    def paths_are_project_relative(cls, value: str) -> str:
        """Reject absolute, parent-traversing, and empty configured paths."""
        normalized = value.replace("\\", "/").strip().rstrip("/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or normalized == "."
            or Path(value).is_absolute()
            or path.is_absolute()
            or ":" in path.parts[0]
            or ".." in path.parts
        ):
            raise ValueError("configured paths must be project-relative without '..'")
        return path.as_posix()

    @model_validator(mode="after")
    def paths_do_not_overlap(self) -> PathsConfig:
        """Keep authoritative and generated directories disjoint."""
        values = {name: PurePosixPath(getattr(self, name)) for name in type(self).model_fields}
        items = list(values.items())
        for index, (left_name, left) in enumerate(items):
            for right_name, right in items[index + 1 :]:
                if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                    raise ValueError(
                        f"configured paths must not overlap: {left_name} and {right_name}"
                    )
        return self


class DefaultsConfig(StrictModel):
    """Defaults applied by interactive clients."""

    language: str = "zh-CN"
    status: QuestionStatus = QuestionStatus.DRAFT
    subject: str = "uncategorized"


class ExportConfig(StrictModel):
    """External export settings."""

    pandoc_command: str = "pandoc"
    reference_docx: str = "templates/reference.docx"

    @field_validator("pandoc_command")
    @classmethod
    def pandoc_command_is_not_empty(cls, value: str) -> str:
        """Reject an empty external command."""
        if not value.strip():
            raise ValueError("pandoc_command must not be empty")
        return value.strip()

    @field_validator("reference_docx")
    @classmethod
    def reference_docx_is_project_relative(cls, value: str) -> str:
        """Keep the optional reference document inside the project."""
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if (
            not normalized
            or Path(value).is_absolute()
            or path.is_absolute()
            or ":" in path.parts[0]
            or ".." in path.parts
        ):
            raise ValueError("reference_docx must be project-relative without '..'")
        return path.as_posix()


class IndexConfig(StrictModel):
    """Search index settings."""

    enabled: bool = True


class AssetEditorCommandConfig(StrictModel):
    """Optional trusted executable used for one built-in editor adapter."""

    command: str | None = None

    @field_validator("command")
    @classmethod
    def command_is_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("asset editor command must not be empty")
        return normalized


class IpeRendererConfig(StrictModel):
    """Optional explicit paths to the two Ipe rendering executables."""

    iperender: str | None = None
    ipetoipe: str | None = None

    @field_validator("iperender", "ipetoipe")
    @classmethod
    def renderer_command_is_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("asset renderer command must not be empty")
        return normalized


class AssetEditorsConfig(StrictModel):
    """Configuration for the built-in Ipe and text editor adapters."""

    ipe: AssetEditorCommandConfig = Field(default_factory=AssetEditorCommandConfig)
    text: AssetEditorCommandConfig = Field(default_factory=AssetEditorCommandConfig)


class AssetRenderersConfig(StrictModel):
    """Configuration for built-in asset renderers."""

    ipe: IpeRendererConfig = Field(default_factory=IpeRendererConfig)


class AssetsConfig(StrictModel):
    """Logical-asset behavior without introducing a plugin framework."""

    editors: AssetEditorsConfig = Field(default_factory=AssetEditorsConfig)
    renderers: AssetRenderersConfig = Field(default_factory=AssetRenderersConfig)
    require_final_for_paper: bool = False
    download_max_bytes: int = Field(default=50 * 1024 * 1024, gt=0)


class ProjectConfig(StrictModel):
    """qbank.yaml structure."""

    schema_version: SchemaVersion
    paths: PathsConfig = Field(default_factory=PathsConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)
    assets: AssetsConfig = Field(default_factory=AssetsConfig)
