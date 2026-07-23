"""Configuration, taxonomy, and diagnostic decision edge coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from qbank import diagnostics
from qbank.diagnostics import _index_checks, _is_within_text, _trigram_check
from qbank.models import (
    AssetEditorCommandConfig,
    ExportConfig,
    IndexHealth,
    IpeRendererConfig,
    PathsConfig,
    QueryFilters,
    SavedView,
    SavedViewRegistry,
    Taxonomy,
    TaxonomyTag,
)


def test_taxonomy_rejects_ambiguous_or_self_referential_identities() -> None:
    with pytest.raises(ValidationError, match="aliases must not be empty"):
        TaxonomyTag(slug="alpha", aliases=[" "])
    with pytest.raises(ValidationError, match="own parent"):
        TaxonomyTag(slug="alpha", parent="alpha")
    with pytest.raises(ValidationError, match="own alias"):
        TaxonomyTag(slug="alpha", aliases=["ALPHA"])
    with pytest.raises(ValidationError, match="slugs must be unique"):
        Taxonomy(tags=[TaxonomyTag(slug="alpha"), TaxonomyTag(slug="alpha")])
    with pytest.raises(ValidationError, match="ambiguous"):
        Taxonomy(
            tags=[
                TaxonomyTag(slug="alpha", name_en="Shared"),
                TaxonomyTag(slug="beta", aliases=["shared"]),
            ]
        )
    with pytest.raises(ValidationError, match="unknown taxonomy parent"):
        Taxonomy(tags=[TaxonomyTag(slug="child", parent="missing")])
    assert Taxonomy(tags=[TaxonomyTag(slug="alpha")]).resolve("missing") is None

    with pytest.raises(ValidationError, match="name must not be empty"):
        SavedView(name=" ", filters=QueryFilters())
    with pytest.raises(ValidationError, match="names must be unique"):
        SavedViewRegistry(views=[SavedView(name="one"), SavedView(name="ONE")])
    with pytest.raises(ValidationError, match="protected views"):
        SavedViewRegistry(views=[SavedView(name="one", protected=True)])


def test_project_command_configuration_rejects_empty_values() -> None:
    with pytest.raises(ValidationError, match="must not overlap"):
        PathsConfig(questions="content", assets="content/assets")
    with pytest.raises(ValidationError, match="pandoc_command"):
        ExportConfig(pandoc_command=" ")
    assert AssetEditorCommandConfig(command=None).command is None
    with pytest.raises(ValidationError, match="must not be empty"):
        AssetEditorCommandConfig(command=" ")
    assert AssetEditorCommandConfig(command=" editor ").command == "editor"
    assert IpeRendererConfig(iperender=None).iperender is None
    with pytest.raises(ValidationError, match="must not be empty"):
        IpeRendererConfig(iperender=" ")
    assert IpeRendererConfig(iperender=" tool ").iperender == "tool"


def test_index_diagnostics_cover_all_health_states(project: tuple[Path, object]) -> None:
    root, _ = project
    context = diagnostics.ProjectContext.from_root(root)
    states = {
        state: _index_checks(
            context,
            IndexHealth(
                state=state,
                updated_at=None,
                documents={},
                message=f"{state} index",
            ),
        )
        for state in ("disabled", "missing", "corrupt", "dirty", "stale", "clean")
    }
    assert states["disabled"][0].status == "WARN"
    assert states["missing"][0].status == "FAIL"
    assert states["corrupt"][0].status == "FAIL"
    assert states["dirty"][1].status == "WARN"
    assert states["stale"][2].status == "WARN"
    assert states["clean"][0].status == "PASS"
    assert not _is_within_text("C:/one", "D:/two")


def test_trigram_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_connect(_database: str) -> sqlite3.Connection:
        raise sqlite3.DatabaseError("no fts")

    monkeypatch.setattr(diagnostics.sqlite3, "connect", fail_connect)
    result = _trigram_check()
    assert result.status == "FAIL" and "no fts" in result.message
