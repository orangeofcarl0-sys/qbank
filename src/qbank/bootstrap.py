"""Single composition root for concrete qbank application services."""

from dataclasses import dataclass

from qbank.application import (
    AssetApplicationService,
    QuestionHistoryService,
    QuestionService,
    SavedViewService,
    StudioQuestionService,
    TagApplicationService,
)
from qbank.application.ports import (
    MutableQuestionRepositoryPort,
    RenderingPort,
    StudioProjectPort,
)
from qbank.composition import create_core_project_services
from qbank.context import ProjectContext
from qbank.diagnostics import DiagnosticServices
from qbank.models import PatchQuestionResult, QuestionPatch
from qbank.operations import (
    MutationServices,
    StudioSaveRequest,
    save_studio_question_in_context,
)
from qbank.rendering import RenderService
from qbank.studio_operations import StudioProjectAdapter
from qbank.taxonomy_store import YamlSavedViewStore, YamlTaxonomyStore
from qbank.view_support import ProjectSpecialViews


@dataclass(frozen=True, slots=True)
class ProjectServices:
    """All concrete application dependencies for one command invocation."""

    repository: MutableQuestionRepositoryPort
    questions: QuestionService
    mutations: MutationServices
    diagnostics: DiagnosticServices
    renderer: RenderingPort
    assets: AssetApplicationService
    tags: TagApplicationService
    views: SavedViewService
    history: QuestionHistoryService
    studio: StudioQuestionService
    studio_project: StudioProjectPort


@dataclass(frozen=True, slots=True)
class StudioQuestionMutationAdapter:
    """Bind Studio's unified save command to transactional adapters."""

    context: ProjectContext
    services: MutationServices
    taxonomy: YamlTaxonomyStore

    def save_question(
        self,
        question_id: str,
        patch: QuestionPatch,
        *,
        dry_run: bool,
        command: str,
    ) -> PatchQuestionResult:
        return save_studio_question_in_context(
            self.context,
            StudioSaveRequest(
                question_id=question_id,
                patch=patch,
                dry_run=dry_run,
                command=command,
            ),
            services=self.services,
            taxonomy=self.taxonomy,
        )


def create_project_services(context: ProjectContext) -> ProjectServices:
    """Wire shared adapters exactly once at the explicit composition root."""
    core = create_core_project_services(context)
    taxonomy = YamlTaxonomyStore(context)
    renderer = RenderService(context)
    return ProjectServices(
        repository=core.repository,
        questions=core.questions,
        mutations=core.mutations,
        diagnostics=core.diagnostics,
        renderer=renderer,
        assets=core.assets,
        tags=core.tags,
        views=SavedViewService(
            repository=core.repository,
            store=YamlSavedViewStore(context),
            special=ProjectSpecialViews(context),
            taxonomy=taxonomy,
            lock=core.lock,
        ),
        history=core.history,
        studio=StudioQuestionService(
            StudioQuestionMutationAdapter(context, core.mutations, taxonomy)
        ),
        studio_project=StudioProjectAdapter(
            context=context,
            questions=core.questions,
            mutations=core.mutations,
            diagnostics=core.diagnostics,
            renderer=renderer,
            assets=core.assets,
            papers=core.papers,
        ),
    )


def create_question_service(context: ProjectContext) -> QuestionService:
    """Compatibility factory returning only the read-oriented service."""
    return create_project_services(context).questions
