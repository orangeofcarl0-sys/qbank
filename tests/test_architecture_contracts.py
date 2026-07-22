"""Executable architecture, extension, and compatibility probes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from qbank.application import QuestionService
from qbank.context import ProjectContext
from qbank.domain import HistoryRecord, QuestionRecord, RepositorySnapshot
from qbank.exporters import EXPORTER_REGISTRY, PlainTextExporter, export_questions
from qbank.models import (
    QUESTION_CONTENT_FIELDS,
    QUESTION_METADATA_FIELDS,
    Diagnostic,
    DiagnosticCode,
    QueryFilters,
    Question,
    SearchHit,
    ValidationReport,
    ValidationSummary,
)
from qbank.operations import MutationServices, add_question_in_context
from qbank.preview import build_preview_in_context
from qbank.storage import parse_question_text, render_question


@dataclass
class InMemoryRepository:
    snapshot: RepositorySnapshot
    scans: int = 0

    def scan(self) -> RepositorySnapshot:
        self.scans += 1
        return self.snapshot


@dataclass
class InMemoryIndex:
    hits: list[SearchHit]
    searched: str | None = None
    rebuilt: RepositorySnapshot | None = None
    checked: RepositorySnapshot | None = None

    def ensure_searchable(self, snapshot: RepositorySnapshot) -> None:
        self.checked = snapshot

    def search(self, text: str, *, limit: int = 20) -> list[SearchHit]:
        self.searched = text
        return self.hits[:limit]

    def rebuild(self, snapshot: RepositorySnapshot) -> int:
        self.rebuilt = snapshot
        return len(snapshot.records)


@dataclass
class InMemoryValidator:
    report: ValidationReport
    snapshot: RepositorySnapshot | None = None

    def validate(
        self,
        *,
        question_id: str | None = None,
        changed: bool = False,
        snapshot: RepositorySnapshot | None = None,
    ) -> ValidationReport:
        del question_id, changed
        self.snapshot = snapshot
        return self.report


@dataclass
class InMemoryMutationRepository:
    snapshot: RepositorySnapshot
    root: Path

    def scan(self) -> RepositorySnapshot:
        return self.snapshot

    def destination(self, question: Question) -> Path:
        return self.root / "questions" / question.subject / f"{question.id}.md"


@dataclass
class InMemoryMutationIndex:
    questions: tuple[Question, ...] = ()
    deleted_ids: tuple[str, ...] = ()
    dirty_reason: str | None = None

    def apply(
        self,
        *,
        questions: tuple[Question, ...] = (),
        deleted_ids: tuple[str, ...] = (),
        topics_by_question: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        del topics_by_question
        self.questions = questions
        self.deleted_ids = deleted_ids

    def mark_dirty(self, reason: str) -> None:
        self.dirty_reason = reason


@dataclass
class InMemoryHistory:
    path: Path
    record: HistoryRecord | None = None

    def prepare(self, record: HistoryRecord) -> tuple[Path, str]:
        self.record = record
        return self.path, "{}\n"


@dataclass
class InMemoryRenderer:
    markdown_calls: int = 0
    template_calls: int = 0

    def markdown_html(self, markdown: str, *, asset_prefix: str | None = None) -> str:
        self.markdown_calls += 1
        return f"<p data-prefix='{asset_prefix or ''}'>{markdown}</p>"

    def html_document(self, *, title: str, language: str, markdown: str) -> str:
        return f"<html lang='{language}'><title>{title}</title>{markdown}</html>"

    def project_template(
        self,
        name: str,
        values: Mapping[str, object],
        *,
        html: bool = False,
    ) -> str:
        del name, html
        self.template_calls += 1
        return str(values)

    def internal_template(
        self,
        name: str,
        values: Mapping[str, object],
    ) -> str:
        del name
        self.template_calls += 1
        return f"<html>{values['cards']}</html>"


def _snapshot(question: Question) -> RepositorySnapshot:
    record = QuestionRecord(
        path=Path(f"{question.id}.md"),
        relative_path=f"questions/{question.subject}/{question.id}.md",
        text=render_question(question),
        question=question,
        duplicate_sections=(),
        metadata=question.model_dump(exclude_none=True),
    )
    return RepositorySnapshot(records=(record,), invalid_sources=(), duplicate_ids=frozenset())


def _service(question: Question) -> tuple[QuestionService, InMemoryRepository, InMemoryIndex]:
    repository = InMemoryRepository(_snapshot(question))
    index = InMemoryIndex(
        [
            SearchHit(
                id=question.id,
                title=question.title,
                chapter=question.chapter or "",
                topics=" ".join(question.topics),
                snippet=question.stem_md,
                rank=0.0,
            )
        ]
    )
    validator = InMemoryValidator(
        ValidationReport(
            ok=True,
            summary=ValidationSummary(questions=1, errors=0, warnings=0),
            issues=[],
        )
    )
    return QuestionService(repository, validator, index), repository, index


def test_direct_application_api_uses_in_memory_ports_without_output(
    question: Question,
    capsys: object,
) -> None:
    service, repository, index = _service(question)

    assert service.query_questions(QueryFilters(subject=question.subject)) == [question]
    assert service.get_question(question.id) == question
    assert service.validate_repository().ok
    assert service.search_questions("interference")[0].id == question.id
    assert service.rebuild_index() == 1
    assert repository.scans == 5
    assert index.searched == "interference"
    assert index.checked is repository.snapshot
    assert index.rebuilt is repository.snapshot
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out == captured.err == ""


def test_mutation_use_case_accepts_composed_non_sqlite_ports(
    project: tuple[Path, object],
    question: Question,
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)  # type: ignore[arg-type]
    repository = InMemoryMutationRepository(
        RepositorySnapshot(records=(), invalid_sources=(), duplicate_ids=frozenset()),
        root,
    )
    index = InMemoryMutationIndex()
    history = InMemoryHistory(root / ".qbank/history/fake.json")
    result = add_question_in_context(
        context,
        question,
        services=MutationServices(repository, index, history),
    )

    assert result.ok and result.index_updated
    assert index.questions[0].id == question.id
    assert history.record is not None
    assert repository.destination(question).is_file()


def test_preview_accepts_a_replacement_rendering_port(
    project: tuple[Path, object],
) -> None:
    root, config = project
    context = ProjectContext.from_config(root, config)  # type: ignore[arg-type]
    renderer = InMemoryRenderer()
    snapshot = RepositorySnapshot(records=(), invalid_sources=(), duplicate_ids=frozenset())

    result = build_preview_in_context(context, snapshot, renderer)

    assert result.ok and result.questions == 0
    assert renderer.template_calls == 1
    assert (root / "build/preview/index.html").read_text(encoding="utf-8") == "<html></html>"


def test_application_layer_contains_no_sqlite_or_presentation_calls() -> None:
    source_root = Path(__file__).parents[1] / "src/qbank/application"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(source_root.glob("*.py"))
    )
    for forbidden in ("sqlite3", "SQLite", "typer", "rich", ".execute(", "print("):
        assert forbidden not in source


def test_plain_text_exporter_is_registered_and_writes_output(
    project: tuple[Path, object],
    question: Question,
) -> None:
    root, config = project
    assert isinstance(EXPORTER_REGISTRY["txt"], PlainTextExporter)
    result = export_questions(
        root,
        config,  # type: ignore[arg-type]
        [question],
        output_format="txt",
        output=Path("exports/questions.txt"),
    )
    text = (root / result.output).read_text(encoding="utf-8")
    assert question.id in text
    assert question.title in text
    assert question.stem_md in text


def test_question_json_markdown_round_trip_is_lossless(question: Question) -> None:
    before = question.model_dump(mode="json", exclude_none=True)
    from_json = Question.model_validate_json(json.dumps(before, ensure_ascii=False))
    markdown = render_question(from_json)
    reparsed, duplicate_sections, _ = parse_question_text(markdown)

    assert duplicate_sections == []
    assert reparsed.model_dump(mode="json", exclude_none=True) == before


def test_question_round_trip_canonicalizes_every_content_boundary(
    question: Question,
) -> None:
    content_updates = {field: f"  canonical {field}  " for field in QUESTION_CONTENT_FIELDS}
    canonical = Question.model_validate({**question.model_dump(), **content_updates})
    reparsed, _, _ = parse_question_text(render_question(canonical))

    assert reparsed == canonical
    assert all(
        getattr(canonical, field) == f"canonical {field}" for field in QUESTION_CONTENT_FIELDS
    )


def test_question_rejects_reserved_section_headings_in_content(
    question: Question,
) -> None:
    with pytest.raises(ValueError, match="reserved qbank section"):
        Question.model_validate(
            {
                **question.model_dump(),
                "stem_md": "Prompt\n\n## 答案\n\nnot a field boundary",
            }
        )


def test_question_layout_exactly_partitions_model_fields() -> None:
    assert tuple(QUESTION_METADATA_FIELDS) + tuple(QUESTION_CONTENT_FIELDS) == tuple(
        Question.model_fields
    )


def test_cli_questions_has_no_direct_storage_or_sqlite_imports() -> None:
    source = (Path(__file__).parents[1] / "src/qbank/commands/questions.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "qbank.repository",
        "qbank.search_index",
        "qbank.storage",
        "sqlite3",
    ):
        assert forbidden not in source


def test_cli_usage_uses_only_public_click_apis() -> None:
    source = (Path(__file__).parents[1] / "src/qbank/cli_usage.py").read_text(encoding="utf-8")
    assert "typer import _click" not in source


def test_desktop_presentation_has_no_direct_authoritative_storage_access() -> None:
    package_root = Path(__file__).parents[1] / "src/qbank"
    presentation_roots = [package_root / "desktop", package_root / "presentation"]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for root in presentation_roots
        for path in sorted(root.rglob("*.py"))
    )
    for forbidden in (
        "qbank.infrastructure",
        "qbank.repository",
        "qbank.search_index",
        "qbank.storage",
        "sqlite3",
        "asset.yaml",
        "index.sqlite",
        ".write_text(",
        ".write_bytes(",
    ):
        assert forbidden not in source


def test_desktop_controller_delegates_project_workflows() -> None:
    source = (Path(__file__).parents[1] / "src/qbank/desktop/controller.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "qbank.application.exchange",
        "qbank.diagnostics",
        "qbank.operations",
        "qbank.papers",
        "qbank.transaction",
        "qbank.yaml_io",
    ):
        assert forbidden not in source


def test_diagnostic_codes_have_one_closed_machine_contract() -> None:
    assert len({item.value for item in DiagnosticCode}) == len(DiagnosticCode)
    for code in DiagnosticCode:
        assert Diagnostic(code=code, message="probe").model_dump(mode="json")["code"] == code.value
    with pytest.raises(ValueError):
        Diagnostic(code="unregistered_code", message="probe")  # type: ignore[arg-type]
