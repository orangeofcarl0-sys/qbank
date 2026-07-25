"""Desktop controller non-visual edge-state coverage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.legacy_qt.controller import DesktopController, _format_from_data_uri
from qbank.models import (
    AssetFormat,
    AssetPackage,
    AssetPackageRepresentation,
    Diagnostic,
    DiagnosticCode,
    QuestionPatch,
    QuestionStatus,
)
from qbank.operations import add_question_in_context
from qbank.rendering import RenderService


def _controller(project: tuple[Path, Any], question: Any) -> DesktopController:
    root, _ = project
    context = ProjectContext.from_root(root)
    services = create_project_services(context)
    add_question_in_context(context, question, services=services.mutations)
    return DesktopController(context, services, RenderService(context))


def test_controller_view_paper_and_legacy_resource_edges(
    project: tuple[Path, Any], question: Any
) -> None:
    controller = _controller(project, question)
    assert not controller._matches_view(question, "draft", set())
    assert controller._matches_view(
        question.model_copy(update={"status": QuestionStatus.DRAFT}), "draft", set()
    )
    assert not controller._matches_view(question, "needs_redraw", set())
    assert controller._matches_view(question, "needs_redraw", {question.id})
    assert not controller._matches_view(question, "paper", set())
    controller.current_paper_ids = (question.id,)
    assert controller._matches_view(question, "paper", set())
    assert controller._matches_view(question, "all", set())

    controller.load_current_paper(None)
    with pytest.raises(DataValidationError, match="select or create"):
        controller.add_to_current_paper([question.id], dry_run=True)
    with pytest.raises(DataValidationError, match="select or create"):
        controller.validate_current_paper()
    with pytest.raises(DataValidationError, match="select or create"):
        controller.build_current_paper(SimpleNamespace())

    remote, root = controller._legacy_representation("https://example.com/image.png")
    assert remote.format == AssetFormat.URL and root == controller.context.root
    with pytest.raises(DataValidationError, match="invalid_resource_uri"):
        controller._legacy_representation("data:image/png;base64,eA==")
    assert _format_from_data_uri("data:image/png;base64,eA==", None) == AssetFormat.PNG
    assert _format_from_data_uri("data:unknown/type;base64,eA==", "figure.svg") == AssetFormat.SVG
    assert _format_from_data_uri("data:unknown/type;base64,eA==", None) == AssetFormat.OTHER


def test_controller_asset_preflight_and_commit_rejections(
    project: tuple[Path, Any], question: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _controller(project, question)
    package = AssetPackage(
        schema_version="1.0",
        question_id=question.id,
        asset_id="figure",
        role="figure",
        representations=[
            AssetPackageRepresentation(
                representation_id="remote",
                format=AssetFormat.PNG,
                url="https://example.com/image.png",
                purpose="reference",
            )
        ],
    )
    patch = QuestionPatch()
    blocking = Diagnostic(
        code=DiagnosticCode.INVALID_RESOURCE_URI,
        message="bad declaration",
    )
    monkeypatch.setattr(
        type(controller.services.questions),
        "patch_question",
        lambda _self, *_args, **_kwargs: SimpleNamespace(ok=False, validation_errors=[blocking]),
    )
    with pytest.raises(DataValidationError, match="bad declaration"):
        controller._preflight_planned_asset_patch(package, patch, "test")
    with pytest.raises(DataValidationError, match="failed validation"):
        controller._commit_question_patch(question.id, patch, "test")

    responses = iter(
        (
            SimpleNamespace(ok=True, validation_errors=[]),
            SimpleNamespace(ok=False, validation_errors=[]),
        )
    )
    monkeypatch.setattr(
        type(controller.services.questions),
        "patch_question",
        lambda _self, *_args, **_kwargs: next(responses),
    )
    with pytest.raises(DataValidationError, match="during commit"):
        controller._commit_question_patch(question.id, patch, "test")


def test_controller_new_asset_id_advances_past_collisions(
    project: tuple[Path, Any], question: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = _controller(project, question)
    monkeypatch.setattr(
        controller.services.assets,
        "list_assets",
        lambda _question: SimpleNamespace(
            assets=[SimpleNamespace(asset_id="figure"), SimpleNamespace(asset_id="figure-2")]
        ),
    )
    assert controller._new_asset_id(question.id, "figure.png") == "figure-3"
    assert controller._new_asset_id(question.id, "***.png") == "figure-3"
