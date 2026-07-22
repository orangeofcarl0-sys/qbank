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
from qbank.context import ProjectContext
from qbank.diagnostics import DiagnosticServices
from qbank.history import JsonHistoryStore
from qbank.infrastructure import (
    AssetInputAdapter,
    FileAssetRepository,
    IpeRenderAdapter,
    RepositoryValidationAdapter,
    SafeAssetLauncher,
)
from qbank.models import PatchQuestionResult, QuestionPatch
from qbank.operations import (
    MutationServices,
    StudioSaveRequest,
    apply_patch_in_context,
    save_studio_question_in_context,
)
from qbank.rendering import RenderService
from qbank.repository import MarkdownQuestionRepository
from qbank.search_index import SQLiteSearchIndex
from qbank.studio_operations import StudioProjectAdapter
from qbank.tagging import AtomicTagMutationExecutor
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
class QuestionMutationAdapter:
    """Bind the context-aware mutation use case to the application port."""

    context: ProjectContext
    services: MutationServices

    def apply_patch(
        self,
        question_id: str,
        patch: QuestionPatch,
        *,
        dry_run: bool,
        command: str,
    ) -> PatchQuestionResult:
        """Apply one validated question patch."""
        return apply_patch_in_context(
            self.context,
            question_id,
            patch,
            services=self.services,
            dry_run=dry_run,
            command=command,
        )


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
    repository = MarkdownQuestionRepository(context)
    index = SQLiteSearchIndex(context)
    validator = RepositoryValidationAdapter(context)
    asset_repository = FileAssetRepository(context)
    history = JsonHistoryStore(context)
    mutations = MutationServices(
        repository=repository,
        index=index,
        history=history,
    )
    taxonomy = YamlTaxonomyStore(context)
    questions = QuestionService(
        repository=repository,
        validator=validator,
        index=index,
        mutations=QuestionMutationAdapter(context, mutations),
    )
    diagnostics = DiagnosticServices(
        repository=repository,
        validator=validator,
        index=index,
    )
    renderer = RenderService(context)
    assets = AssetApplicationService(
        repository=asset_repository,
        inputs=AssetInputAdapter(context),
        renderer=IpeRenderAdapter(context),
        launcher=SafeAssetLauncher(context),
    )
    return ProjectServices(
        repository=repository,
        questions=questions,
        mutations=mutations,
        diagnostics=diagnostics,
        renderer=renderer,
        assets=assets,
        tags=TagApplicationService(
            repository=repository,
            taxonomy=taxonomy,
            mutations=AtomicTagMutationExecutor(context, mutations),
        ),
        views=SavedViewService(
            repository=repository,
            store=YamlSavedViewStore(context),
            special=ProjectSpecialViews(context),
            taxonomy=taxonomy,
        ),
        history=QuestionHistoryService(history),
        studio=StudioQuestionService(StudioQuestionMutationAdapter(context, mutations, taxonomy)),
        studio_project=StudioProjectAdapter(
            context=context,
            questions=questions,
            mutations=mutations,
            diagnostics=diagnostics,
            renderer=renderer,
            assets=assets,
        ),
    )


def create_question_service(context: ProjectContext) -> QuestionService:
    """Compatibility factory returning only the read-oriented service."""
    return create_project_services(context).questions
