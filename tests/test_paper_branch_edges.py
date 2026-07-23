"""Paper compatibility and validation edge decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import qbank.papers as papers
from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.errors import DataValidationError, ExportError
from qbank.models import (
    Diagnostic,
    Paper,
    PaperBuildOptions,
    PaperBuildRequest,
    QuestionStatus,
)
from qbank.operations import add_question_in_context


def test_paper_option_and_request_compatibility_edges(tmp_path: Path) -> None:
    options = PaperBuildOptions()
    assert papers._paper_options(options, {}) is options
    with pytest.raises(DataValidationError, match="not both"):
        papers._paper_options(options, {"with_answers": False})
    with pytest.raises(DataValidationError):
        papers._paper_options(None, {"unknown": True})

    request = PaperBuildRequest(output_format="html")
    assert papers._paper_request(request, {}) is request
    with pytest.raises(DataValidationError, match="not both"):
        papers._paper_request(request, {"output_format": "md"})
    with pytest.raises(ExportError, match="unsupported paper format"):
        papers._paper_request(None, {"output_format": "pdf"})
    legacy = papers._paper_request(
        None,
        {"output_format": "md", "output": tmp_path / "paper.md", "with_answers": False},
    )
    assert legacy.output_format == "md" and not legacy.options.with_answers


def test_unique_diagnostics_and_pandoc_platform_parsing(
    project: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    issue = Diagnostic(code="invalid_source_file", message="broken")
    assert papers._unique_diagnostics([issue, issue]) == [issue]
    context = ProjectContext.from_root(root)
    monkeypatch.setattr(papers.os, "name", "posix")
    assert papers.pandoc_command(context.config) == ["pandoc"]


def test_paper_validation_reports_deprecated_question(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    question = make_question(id="Q-PAPER-EDGE-1", status=QuestionStatus.DEPRECATED)
    services = create_project_services(context)
    add_question_in_context(context, question, services=services.mutations)
    paper = Paper.model_validate(
        {
            "schema_version": "1.0",
            "title": "Deprecated",
            "sections": [{"title": "S", "questions": [{"id": question.id, "score": 1}]}],
        }
    )
    report = papers.validate_paper_in_context(
        context,
        paper,
        allow_deprecated=False,
        snapshot=services.repository.scan(),
        assets=services.assets,
    )
    assert any(issue.code == "deprecated_question" for issue in report.issues)
