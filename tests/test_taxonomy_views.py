"""Project-level taxonomy, bulk topic, saved-view, and CLI regressions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.bootstrap import create_project_services
from qbank.cli import app
from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.models import QueryFilters, TagStatus, Taxonomy
from qbank.operations import add_question_in_context
from qbank.taxonomy_store import YamlTaxonomyStore
from qbank.yaml_io import load_yaml


def _add(
    root: Path,
    make_question: Any,
    *,
    question_id: str,
    topics: list[str],
    title: str,
    chapter: str,
) -> None:
    context = ProjectContext.from_root(root)
    add_question_in_context(
        context,
        make_question(
            id=question_id,
            topics=topics,
            title=title,
            chapter=chapter,
        ),
        services=create_project_services(context).mutations,
    )


def test_init_includes_empty_versionable_taxonomy_and_views(project: tuple[Path, Any]) -> None:
    root, _ = project
    assert (
        Taxonomy.model_validate(
            load_yaml((root / "taxonomy.yaml").read_text(encoding="utf-8"))
        ).tags
        == []
    )
    assert (root / "views.yaml").read_text(encoding="utf-8").startswith("schema_version:")


def test_normalize_then_rename_is_atomic_and_preserves_alias(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, _ = project
    _add(
        root,
        make_question,
        question_id="OPT-TAG-0001",
        topics=["Interference", "optical-path"],
        title="Interference one",
        chapter="waves",
    )
    context = ProjectContext.from_root(root)
    service = create_project_services(context).tags
    taxonomy_before = (root / "taxonomy.yaml").read_bytes()
    source = next((root / "questions").rglob("OPT-TAG-0001.md"))
    source_before = source.read_bytes()

    planned = service.normalize(dry_run=True, command="test normalize")
    assert planned.affected_questions == 1
    assert source.read_bytes() == source_before
    assert (root / "taxonomy.yaml").read_bytes() == taxonomy_before

    normalized = service.normalize(dry_run=False, command="test normalize")
    assert normalized.index_updated is True
    assert {tag.slug for tag in normalized.taxonomy_after} == {
        "interference",
        "optical-path",
    }
    assert all(tag.status == TagStatus.PENDING for tag in normalized.taxonomy_after)

    renamed = service.rename(
        "interference",
        "wave-interference",
        dry_run=False,
        command="test rename",
    )
    entry = YamlTaxonomyStore(context).load().by_slug()["wave-interference"]
    assert "interference" in entry.aliases
    assert renamed.changes[0].after == ["wave-interference", "optical-path"]
    assert renamed.history_token
    reloaded = create_project_services(ProjectContext.from_root(root)).questions.get_question(
        "OPT-TAG-0001"
    )
    assert reloaded.topics == ["wave-interference", "optical-path"]
    assert any(
        path.name.startswith(renamed.history_token) for path in (root / ".qbank/history").iterdir()
    )


def test_merge_delete_and_bulk_edit_keep_topics_valid(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, _ = project
    _add(
        root,
        make_question,
        question_id="OPT-TAG-0001",
        topics=["fft", "fourier"],
        title="FFT aliases",
        chapter="signals",
    )
    _add(
        root,
        make_question,
        question_id="OPT-TAG-0002",
        topics=["fft"],
        title="FFT only",
        chapter="signals",
    )
    context = ProjectContext.from_root(root)
    service = create_project_services(context).tags
    service.normalize(dry_run=False, command="test normalize")
    merged = service.merge("fourier", "fft", dry_run=False, command="test merge")
    assert merged.affected_questions == 1
    assert "fourier" in YamlTaxonomyStore(context).load().by_slug()["fft"].aliases

    bulk = service.bulk_edit(
        ["OPT-TAG-0001", "OPT-TAG-0002"],
        add=["signal-processing"],
        remove=["fft"],
        dry_run=False,
        command="test bulk",
    )
    assert bulk.affected_questions == 2
    assert all(change.after == ["signal-processing"] for change in bulk.changes)
    with pytest.raises(DataValidationError, match="without topics"):
        service.delete("signal-processing", dry_run=True, command="test delete")


def test_tag_stats_cooccurrence_and_alias_autocomplete(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, _ = project
    for question_id, topics in (
        ("OPT-TAG-0001", ["alpha", "beta"]),
        ("OPT-TAG-0002", ["alpha", "gamma"]),
        ("OPT-TAG-0003", ["alpha", "beta"]),
    ):
        _add(
            root,
            make_question,
            question_id=question_id,
            topics=topics,
            title=question_id,
            chapter="facet",
        )
    context = ProjectContext.from_root(root)
    service = create_project_services(context).tags
    service.normalize(dry_run=False, command="test normalize")
    entry = (
        YamlTaxonomyStore(context)
        .load()
        .by_slug()["alpha"]
        .model_copy(update={"name_zh": "阿尔法", "name_en": "Alpha", "aliases": ["first"]})
    )
    service.update_tag(entry, dry_run=False, command="test metadata")

    assert service.suggestions("阿尔")[0].slug == "alpha"
    assert service.suggestions("first")[0].count == 3
    pairs = {(item.left, item.right): item.count for item in service.cooccurrence(top_n=3)}
    assert pairs[("alpha", "beta")] == 2
    assert pairs[("alpha", "gamma")] == 1
    overview = service.overview(top_n=3)
    assert {cell.axis for cell in overview.chapter_coverage} == {"facet"}
    assert {cell.tag for cell in overview.year_coverage} == {"alpha", "beta", "gamma"}


def test_tag_history_token_supports_safe_atomic_undo(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, _ = project
    _add(
        root,
        make_question,
        question_id="OPT-TAG-0001",
        topics=["old-tag", "stable"],
        title="Undo tags",
        chapter="history",
    )
    context = ProjectContext.from_root(root)
    service = create_project_services(context).tags
    service.normalize(dry_run=False, command="test normalize")
    renamed = service.rename("old-tag", "new-tag", dry_run=False, command="test rename")
    assert renamed.history_token is not None

    planned = service.undo(renamed.history_token, dry_run=True, command="test undo")
    assert planned.changes[0].after == ["old-tag", "stable"]
    service.undo(renamed.history_token, dry_run=False, command="test undo")
    question = create_project_services(ProjectContext.from_root(root)).questions.get_question(
        "OPT-TAG-0001"
    )
    assert question.topics == ["old-tag", "stable"]


def test_saved_view_combines_text_topics_exclusion_and_persists(
    project: tuple[Path, Any], make_question: Any
) -> None:
    root, _ = project
    _add(
        root,
        make_question,
        question_id="OPT-TAG-0001",
        topics=["alpha", "beta"],
        title="Michelson interferometer",
        chapter="waves",
    )
    _add(
        root,
        make_question,
        question_id="OPT-TAG-0002",
        topics=["alpha", "legacy"],
        title="Michelson legacy",
        chapter="waves",
    )
    context = ProjectContext.from_root(root)
    views = create_project_services(context).views
    filters = QueryFilters(
        text="Michelson",
        chapter="waves",
        topics=["alpha", "beta"],
        excluded_topics=["legacy"],
        topic_mode="and",
    )
    dry_run = views.save("clean-interference", filters, dry_run=True)
    assert dry_run.dry_run is True
    assert "clean-interference" not in {view.name for view in views.list_views()}
    views.save("clean-interference", filters, dry_run=False)

    reloaded = create_project_services(ProjectContext.from_root(root)).views
    assert [question.id for question in reloaded.apply("clean-interference")] == ["OPT-TAG-0001"]
    renamed = reloaded.rename("clean-interference", "clean", dry_run=False)
    assert renamed.view.name == "clean"
    reloaded.delete("clean", dry_run=False)
    assert "clean" not in {view.name for view in reloaded.list_views()}
    with pytest.raises(DataValidationError, match="built-in"):
        reloaded.delete("all", dry_run=True)


def test_tag_and_view_cli_json_contracts(
    project: tuple[Path, Any],
    make_question: Any,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = project
    _add(
        root,
        make_question,
        question_id="OPT-TAG-0001",
        topics=["alpha", "beta"],
        title="CLI tags",
        chapter="cli",
    )
    monkeypatch.chdir(root)
    normalized = runner.invoke(app, ["tag", "normalize", "--dry-run", "--format", "json"])
    assert normalized.exit_code == 0
    payload = json.loads(normalized.stdout)
    assert payload["dry_run"] is True
    assert payload["affected_questions"] == 0
    assert {tag["slug"] for tag in payload["taxonomy_after"]} == {"alpha", "beta"}

    assert runner.invoke(app, ["tag", "normalize", "--format", "json"]).exit_code == 0
    stats = runner.invoke(app, ["tag", "stats", "--format", "json"])
    assert {row["slug"] for row in json.loads(stats.stdout)} == {"alpha", "beta"}
    saved = runner.invoke(
        app,
        [
            "view",
            "save",
            "alpha-only",
            "--topic",
            "alpha",
            "--exclude-topic",
            "legacy",
            "--format",
            "json",
        ],
    )
    assert saved.exit_code == 0
    applied = runner.invoke(app, ["view", "apply", "alpha-only", "--format", "json"])
    assert [row["id"] for row in json.loads(applied.stdout)] == ["OPT-TAG-0001"]

    listed = runner.invoke(app, ["tag", "list", "--search", "alpha", "--format", "json"])
    assert json.loads(listed.stdout)[0]["slug"] == "alpha"
    shown = runner.invoke(app, ["tag", "show", "alpha", "--format", "json"])
    assert json.loads(shown.stdout)["count"] == 1
    cooccur = runner.invoke(app, ["tag", "cooccur", "--top-n", "2", "--format", "json"])
    assert json.loads(cooccur.stdout)[0]["count"] == 1

    renamed_tag = runner.invoke(app, ["tag", "rename", "alpha", "primary", "--format", "json"])
    assert renamed_tag.exit_code == 0
    merged_tag = runner.invoke(app, ["tag", "merge", "beta", "primary", "--format", "json"])
    assert merged_tag.exit_code == 0
    deleted_tag = runner.invoke(app, ["tag", "delete", "primary", "--dry-run", "--format", "json"])
    assert deleted_tag.exit_code == 3

    views = runner.invoke(app, ["view", "list", "--format", "json"])
    assert "alpha-only" in {row["name"] for row in json.loads(views.stdout)}
    renamed_view = runner.invoke(
        app,
        ["view", "rename", "alpha-only", "primary-only", "--format", "json"],
    )
    assert renamed_view.exit_code == 0
    deleted_view = runner.invoke(app, ["view", "delete", "primary-only", "--format", "json"])
    assert deleted_view.exit_code == 0
