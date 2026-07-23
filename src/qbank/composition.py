"""Shared non-presentation composition for CLI, MCP, and Studio adapters."""

from __future__ import annotations

from dataclasses import dataclass

from qbank.application import (
    AssetApplicationService,
    QuestionHistoryService,
    QuestionService,
    TagApplicationService,
)
from qbank.application.ports import MutableQuestionRepositoryPort
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
from qbank.operations import MutationServices, apply_patch_in_context
from qbank.repository import MarkdownQuestionRepository
from qbank.search_index import SQLiteSearchIndex
from qbank.tagging import AtomicTagMutationExecutor
from qbank.taxonomy_store import YamlTaxonomyStore


@dataclass(frozen=True, slots=True)
class CoreProjectServices:
    """Presentation-neutral services shared by every local interface."""

    repository: MutableQuestionRepositoryPort
    questions: QuestionService
    mutations: MutationServices
    diagnostics: DiagnosticServices
    assets: AssetApplicationService
    tags: TagApplicationService
    history: QuestionHistoryService


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
        return apply_patch_in_context(
            self.context,
            question_id,
            patch,
            services=self.services,
            dry_run=dry_run,
            command=command,
        )


def create_core_project_services(context: ProjectContext) -> CoreProjectServices:
    """Wire the single shared implementation used by CLI, MCP, and Studio."""
    repository = MarkdownQuestionRepository(context)
    index = SQLiteSearchIndex(context)
    validator = RepositoryValidationAdapter(context)
    history_store = JsonHistoryStore(context)
    mutations = MutationServices(repository=repository, index=index, history=history_store)
    taxonomy = YamlTaxonomyStore(context)
    questions = QuestionService(
        repository=repository,
        validator=validator,
        index=index,
        mutations=QuestionMutationAdapter(context, mutations),
    )
    assets = AssetApplicationService(
        repository=FileAssetRepository(context),
        inputs=AssetInputAdapter(context),
        renderer=IpeRenderAdapter(context),
        launcher=SafeAssetLauncher(context),
    )
    return CoreProjectServices(
        repository=repository,
        questions=questions,
        mutations=mutations,
        diagnostics=DiagnosticServices(repository=repository, validator=validator, index=index),
        assets=assets,
        tags=TagApplicationService(
            repository=repository,
            taxonomy=taxonomy,
            mutations=AtomicTagMutationExecutor(context, mutations),
        ),
        history=QuestionHistoryService(history_store),
    )
