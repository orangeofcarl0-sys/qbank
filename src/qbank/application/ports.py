"""Internal ports consumed by application services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from qbank.domain import (
    AssetHistoryEvent,
    AssetLocation,
    HistoryRecord,
    NormalizedAssetInput,
    RenderedAsset,
    RepositorySnapshot,
)
from qbank.models import (
    AssetFormat,
    AssetHistoryEntry,
    AssetManifest,
    AssetPackageRepresentation,
    Diagnostic,
    IndexHealth,
    PatchQuestionResult,
    Question,
    QuestionPatch,
    SearchHit,
    ValidationReport,
)


class QuestionRepositoryPort(Protocol):
    """Read access to one authoritative repository snapshot."""

    def scan(self) -> RepositorySnapshot: ...


class MutableQuestionRepositoryPort(QuestionRepositoryPort, Protocol):
    """Repository operations required to plan authoritative mutations."""

    def destination(self, question: Question) -> Path: ...


class QuestionIndexPort(Protocol):
    """Search projection behavior used by the application layer."""

    def ensure_searchable(self, snapshot: RepositorySnapshot) -> None: ...

    def search(self, text: str, *, limit: int = 20) -> list[SearchHit]: ...

    def rebuild(self, snapshot: RepositorySnapshot) -> int: ...


class MutationIndexPort(Protocol):
    """Incremental index behavior used after authoritative commits."""

    def apply(
        self,
        *,
        questions: tuple[Question, ...] = (),
        deleted_ids: tuple[str, ...] = (),
        topics_by_question: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None: ...

    def mark_dirty(self, reason: str) -> None: ...


class QuestionMutationPort(Protocol):
    """Structured authoritative question mutations used by interactive clients."""

    def apply_patch(
        self,
        question_id: str,
        patch: QuestionPatch,
        *,
        dry_run: bool,
        command: str,
    ) -> PatchQuestionResult: ...


class IndexHealthPort(Protocol):
    """Read-only projection health consumed by diagnostics."""

    def health(self, snapshot: RepositorySnapshot | None = None) -> IndexHealth: ...


class HistoryStorePort(Protocol):
    """Prepare history content for the same transaction as source files."""

    def prepare(self, record: HistoryRecord) -> tuple[Path, str]: ...


class RenderingPort(Protocol):
    """Sandboxed Markdown and template rendering used by artifact use cases."""

    def markdown_html(
        self,
        markdown: str,
        *,
        asset_prefix: str | None = None,
    ) -> str: ...

    def html_document(
        self,
        *,
        title: str,
        language: str,
        markdown: str,
    ) -> str: ...

    def project_template(
        self,
        name: str,
        values: Mapping[str, object],
        *,
        html: bool = False,
    ) -> str: ...

    def internal_template(
        self,
        name: str,
        values: Mapping[str, object],
    ) -> str: ...


class RepositoryValidatorPort(Protocol):
    """Repository validation independent of presentation output."""

    def validate(
        self,
        *,
        question_id: str | None = None,
        changed: bool = False,
        snapshot: RepositorySnapshot | None = None,
    ) -> ValidationReport: ...


class AssetRepositoryPort(Protocol):
    """Authoritative logical-asset manifests, files, and operation history."""

    def list(
        self,
        question_id: str | None = None,
        *,
        strict: bool = True,
    ) -> tuple[AssetManifest, ...]: ...

    def get(self, question_id: str, asset_id: str) -> AssetManifest: ...

    def find_by_reference(
        self,
        question_id: str,
        reference: str,
    ) -> AssetManifest | None: ...

    def location(self, question_id: str, asset_id: str) -> AssetLocation: ...

    def representation_path(
        self,
        manifest: AssetManifest,
        representation_id: str,
    ) -> Path | None: ...

    def commit(
        self,
        manifest: AssetManifest,
        files: Mapping[str, bytes],
        event: AssetHistoryEvent,
    ) -> None: ...

    def record(self, event: AssetHistoryEvent) -> None: ...

    def discard_new(self, question_id: str, asset_id: str) -> None: ...

    def history(
        self,
        question_id: str,
        asset_id: str | None = None,
    ) -> tuple[AssetHistoryEntry, ...]: ...

    def diagnostics(self) -> tuple[Diagnostic, ...]: ...


class AssetInputPort(Protocol):
    """Normalize package sources while preserving bytes and provenance."""

    def normalize(
        self,
        representation: AssetPackageRepresentation,
        *,
        package_root: Path,
        download: bool = False,
    ) -> NormalizedAssetInput: ...


class AssetRendererPort(Protocol):
    """Render registered editable source formats through built-in adapters."""

    def render(
        self,
        source: Path,
        formats: Sequence[AssetFormat],
        *,
        execute: bool,
    ) -> tuple[RenderedAsset, ...]: ...


class AssetLauncherPort(Protocol):
    """Open only repository-resolved files with trusted built-in adapters."""

    def open_file(self, path: Path, *, execute: bool) -> tuple[str, ...]: ...

    def open_url(self, url: str, *, execute: bool) -> tuple[str, ...]: ...

    def open_directory(self, path: Path, *, execute: bool) -> tuple[str, ...]: ...

    def edit_file(
        self,
        path: Path,
        format_: AssetFormat,
        *,
        execute: bool,
    ) -> tuple[str, ...]: ...
