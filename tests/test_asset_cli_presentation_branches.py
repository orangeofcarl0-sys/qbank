"""Asset CLI table/JSON presentation compatibility coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.bootstrap import create_project_services
from qbank.cli import app
from qbank.commands.assets import _emit_mutation
from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.models import (
    AssetFormat,
    AssetMutationResult,
    AssetPackage,
    AssetPackageRepresentation,
)
from qbank.operations import add_question_in_context


def test_asset_list_show_and_validate_support_table_and_json(
    project: tuple[Path, Any],
    question: Any,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    services = create_project_services(context)
    add_question_in_context(context, question, services=services.mutations)
    service = services.assets
    package = AssetPackage(
        schema_version="1.0",
        question_id=question.id,
        asset_id="remote",
        role="reference",
        suggested_render="web",
        representations=[
            AssetPackageRepresentation(
                representation_id="web",
                format=AssetFormat.PNG,
                url="https://example.com/image.png",
                purpose="reference",
            )
        ],
    )
    service.ingest_package(package, root, dry_run=False)
    monkeypatch.chdir(root)
    for command in (
        ["asset", "list", question.id, "--format", "table"],
        ["asset", "list", question.id, "--format", "json"],
        ["asset", "show", question.id, "remote", "--format", "table"],
        ["asset", "show", question.id, "remote", "--format", "json"],
        ["asset", "validate", "--format", "table"],
        ["asset", "validate", "--format", "json"],
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output


def test_asset_mutation_output_rejects_unknown_format(capsys: pytest.CaptureFixture[str]) -> None:
    result = AssetMutationResult(
        ok=True,
        dry_run=True,
        action="normalize",
        question_id="Q-1",
        asset_id="figure",
        manifest_path="assets/Q-1/figure/asset.yaml",
        representations=[],
        warnings=[],
    )
    _emit_mutation(result, "table")
    assert "normalize" in capsys.readouterr().out
    _emit_mutation(result, "json")
    assert '"ok": true' in capsys.readouterr().out
    with pytest.raises(DataValidationError, match="unsupported output format"):
        _emit_mutation(result, "yaml")
