"""Single composition root for concrete qbank application services."""

from dataclasses import dataclass

from qbank.application import AssetApplicationService, QuestionService
from qbank.application.ports import MutableQuestionRepositoryPort, RenderingPort
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
from qbank.operations import MutationServices
from qbank.rendering import RenderService
from qbank.repository import MarkdownQuestionRepository
from qbank.search_index import SQLiteSearchIndex


@dataclass(frozen=True, slots=True)
class ProjectServices:
    """All concrete application dependencies for one command invocation."""

    repository: MutableQuestionRepositoryPort
    questions: QuestionService
    mutations: MutationServices
    diagnostics: DiagnosticServices
    renderer: RenderingPort
    assets: AssetApplicationService


def create_project_services(context: ProjectContext) -> ProjectServices:
    """Wire shared adapters exactly once at the explicit composition root."""
    repository = MarkdownQuestionRepository(context)
    index = SQLiteSearchIndex(context)
    validator = RepositoryValidationAdapter(context)
    asset_repository = FileAssetRepository(context)
    return ProjectServices(
        repository=repository,
        questions=QuestionService(
            repository=repository,
            validator=validator,
            index=index,
        ),
        mutations=MutationServices(
            repository=repository,
            index=index,
            history=JsonHistoryStore(context),
        ),
        diagnostics=DiagnosticServices(
            repository=repository,
            validator=validator,
            index=index,
        ),
        renderer=RenderService(context),
        assets=AssetApplicationService(
            repository=asset_repository,
            inputs=AssetInputAdapter(context),
            renderer=IpeRenderAdapter(context),
            launcher=SafeAssetLauncher(context),
        ),
    )


def create_question_service(context: ProjectContext) -> QuestionService:
    """Compatibility factory returning only the read-oriented service."""
    return create_project_services(context).questions
