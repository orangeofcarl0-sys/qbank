"""Concrete Studio project workflows shared through application ports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qbank.application import AssetApplicationService, QuestionService
from qbank.application.exchange import load_json_records
from qbank.application.ports import RenderingPort
from qbank.context import ProjectContext
from qbank.diagnostics import DiagnosticServices, project_status_in_context
from qbank.errors import ConflictError, DataValidationError
from qbank.models import (
    AddQuestionResult,
    DeleteQuestionResult,
    IngestOptions,
    IngestResult,
    Paper,
    PaperBuildRequest,
    PaperBuildResult,
    PaperQuestion,
    PaperSection,
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
from qbank.papers import build_paper_in_context, load_paper, validate_paper_in_context
from qbank.transaction import MutationTransaction
from qbank.yaml_io import dump_yaml


@dataclass(frozen=True, slots=True)
class StudioProjectAdapter:
    """Execute project workflows without exposing infrastructure to Qt controllers."""

    context: ProjectContext
    questions: QuestionService
    mutations: MutationServices
    diagnostics: DiagnosticServices
    renderer: RenderingPort
    assets: AssetApplicationService

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
        return sorted(self.context.paths.papers.rglob("*.yaml"), key=lambda item: item.as_posix())

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
        target = self._paper_path(path)
        if target.exists():
            raise ConflictError(f"paper file already exists: {target}")
        paper = Paper(
            schema_version="1.0",
            title=title,
            sections=[
                PaperSection(
                    title="题目",
                    questions=[PaperQuestion(id=value, score=1) for value in question_ids],
                )
            ],
        )
        self._require_valid_paper(paper)
        if not dry_run:
            self._write_paper(target, paper)
        return paper

    def add_to_paper(self, path: Path, question_ids: list[str], *, dry_run: bool) -> Paper:
        target = self._paper_path(path)
        paper = load_paper(target)
        known = {item.id for section in paper.sections for item in section.questions}
        additions = [
            PaperQuestion(id=value, score=1) for value in question_ids if value not in known
        ]
        first = paper.sections[0]
        sections = [first.model_copy(update={"questions": [*first.questions, *additions]})]
        sections.extend(paper.sections[1:])
        updated = paper.model_copy(update={"sections": sections})
        self._require_valid_paper(updated)
        if not dry_run:
            self._write_paper(target, updated)
        return updated

    def validate_paper(self, path: Path) -> PaperValidationReport:
        return validate_paper_in_context(
            self.context,
            load_paper(self._paper_path(path)),
            assets=self.assets,
        )

    def build_paper(self, path: Path, request: PaperBuildRequest) -> PaperBuildResult:
        return build_paper_in_context(
            self.context,
            self._paper_path(path),
            request,
            renderer=self.renderer,
            assets=self.assets,
        )

    def _paper_path(self, path: Path) -> Path:
        target = path.resolve()
        if not target.is_relative_to(self.context.paths.papers.resolve()):
            raise DataValidationError("paper file must be inside the configured papers directory")
        return target

    def _require_valid_paper(self, paper: Paper) -> None:
        report = validate_paper_in_context(self.context, paper, assets=self.assets)
        if not report.ok:
            raise DataValidationError(f"paper validation failed: {report.issues}")

    @staticmethod
    def _write_paper(path: Path, paper: Paper) -> None:
        transaction = MutationTransaction()
        transaction.write(path, dump_yaml(paper.model_dump(mode="json", exclude_none=True)) + "\n")
        transaction.commit()
