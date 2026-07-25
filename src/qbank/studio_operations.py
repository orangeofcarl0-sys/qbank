"""Concrete Studio project workflows shared through application ports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qbank.application import AssetApplicationService, QuestionService
from qbank.application.exchange import load_json_records
from qbank.application.ports import RenderingPort
from qbank.context import ProjectContext
from qbank.diagnostics import DiagnosticServices, project_status_in_context
from qbank.models import (
    AddQuestionResult,
    DeleteQuestionResult,
    IngestOptions,
    IngestResult,
    Paper,
    PaperBuildRequest,
    PaperBuildResult,
    PaperValidationReport,
    Question,
    StatusResult,
)
from qbank.operations import (
    MutationServices,
    add_question_in_context,
    delete_question_in_context,
    ingest_questions_in_context,
)
from qbank.paper_service import PaperApplicationService
from qbank.papers import build_paper_in_context, load_paper


@dataclass(frozen=True, slots=True)
class StudioProjectAdapter:
    """Execute project workflows without exposing infrastructure to Qt controllers."""

    context: ProjectContext
    questions: QuestionService
    mutations: MutationServices
    diagnostics: DiagnosticServices
    renderer: RenderingPort
    assets: AssetApplicationService
    papers: PaperApplicationService

    def status(self) -> StatusResult:
        return project_status_in_context(self.context, self.diagnostics)

    def create_question(self, question_id: str, title: str, *, dry_run: bool) -> AddQuestionResult:
        question = Question.model_validate(
            {
                "schema_version": "1.0",
                "id": question_id,
                "title": title,
                "type": "other",
                "subject": self.context.config.defaults.subject,
                "topics": ["unclassified"],
                "difficulty": 1,
                "status": "draft",
                "language": self.context.config.defaults.language,
                "source": {"type": "manual"},
                "assets": [],
                "stem_md": "请填写题干。",
            }
        )
        return add_question_in_context(
            self.context,
            question,
            services=self.mutations,
            dry_run=dry_run,
            command="qbank desktop new question",
        )

    def copy_question(self, source_id: str, new_id: str, *, dry_run: bool) -> AddQuestionResult:
        source = self.questions.get_question(source_id)
        copy = Question.model_validate(
            {
                **source.model_dump(mode="json"),
                "id": new_id,
                "title": f"{source.title}（副本）",
                "status": "draft",
                "created_at": None,
                "updated_at": None,
            }
        )
        return add_question_in_context(
            self.context,
            copy,
            services=self.mutations,
            dry_run=dry_run,
            command="qbank desktop copy question",
        )

    def import_questions(self, path: Path, *, dry_run: bool) -> IngestResult:
        questions = load_json_records(
            path.read_text(encoding="utf-8-sig"),
            jsonl=path.suffix.casefold() == ".jsonl",
        )
        return ingest_questions_in_context(
            self.context,
            questions,
            services=self.mutations,
            options=IngestOptions(dry_run=dry_run, command="qbank desktop import"),
        )

    def delete_question(self, question_id: str, *, dry_run: bool) -> DeleteQuestionResult:
        return delete_question_in_context(
            self.context,
            question_id,
            services=self.mutations,
            dry_run=dry_run,
            command="qbank desktop delete question",
        )

    def list_papers(self) -> list[Path]:
        return self.papers.list()

    def paper_ids(self, path: Path) -> tuple[str, ...]:
        paper = load_paper(self._paper_path(path))
        return tuple(item.id for section in paper.sections for item in section.questions)

    def create_paper(
        self,
        path: Path,
        title: str,
        question_ids: list[str],
        *,
        dry_run: bool,
    ) -> Paper:
        return self.papers.create(
            path,
            title,
            question_ids,
            dry_run=dry_run,
            command="qbank desktop create paper",
        )

    def add_to_paper(self, path: Path, question_ids: list[str], *, dry_run: bool) -> Paper:
        return self.papers.add_questions(
            path,
            question_ids,
            dry_run=dry_run,
            command="qbank desktop add to paper",
        )

    def validate_paper(self, path: Path) -> PaperValidationReport:
        return self.papers.validate(load_paper(self._paper_path(path)))

    def build_paper(self, path: Path, request: PaperBuildRequest) -> PaperBuildResult:
        return build_paper_in_context(
            self.context,
            self._paper_path(path),
            request,
            renderer=self.renderer,
            assets=self.assets,
        )

    def paper_path(self, path: Path) -> Path:
        """Resolve a paper path through the shared paper application service."""
        return self.papers.resolve(path)

    def _paper_path(self, path: Path) -> Path:
        return self.paper_path(path)
