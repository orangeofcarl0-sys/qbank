"""Meaningful edge-state coverage for application-layer decision branches."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qbank.application.assets import (
    AssetApplicationService,
    NormalizedAssetInput,
    PureSuffix,
    _editable_parent,
    _editor_representation,
    _ipe_source,
    _merge_rendered,
    _next_edit_identifier,
    _optional_representation,
    _reconciled_editor_manifest,
    _render_parent,
    _render_preference,
    _representation,
    _restored_manifest,
    _versioned_replacement,
)
from qbank.application.service import QuestionService
from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.domain import AssetHistoryEvent, RenderedAsset
from qbank.errors import AssetConflictError, AssetNotFoundError, ConflictError, DataValidationError
from qbank.models import (
    AssetFormat,
    AssetManifest,
    AssetRepresentation,
    AssetStatus,
    QueryFilters,
    QuestionPatch,
)
from qbank.operations import add_question_in_context


def _rep(  # noqa: PLR0913
    identifier: str,
    format_: AssetFormat,
    *,
    purpose: str = "render",
    editable: bool = False,
    derived_from: str | None = None,
    stale: bool = False,
    digest: str | None = "0" * 64,
    metadata: dict[str, object] | None = None,
) -> AssetRepresentation:
    return AssetRepresentation(
        representation_id=identifier,
        format=format_,
        path=f"{identifier}.{format_.value}",
        purpose=purpose,
        editable=editable,
        derived_from=derived_from,
        stale=stale,
        content_hash=digest,
        metadata=metadata or {},
    )


def _manifest(
    representations: list[AssetRepresentation],
    *,
    editor: str | None = None,
    render: str | None = None,
) -> AssetManifest:
    return AssetManifest(
        schema_version="1.0",
        question_id="OPT-EDGE-0001",
        asset_id="figure",
        role="figure",
        status=AssetStatus.EDITING,
        preferred_editor=editor,
        preferred_render=render,
        representations=representations,
    )


def test_asset_representation_selection_and_version_edges() -> None:
    png = _rep("png", AssetFormat.PNG, purpose="original")
    svg = _rep("svg", AssetFormat.SVG, editable=True)
    ipe = _rep("ipe", AssetFormat.IPE, editable=True)
    manifest = _manifest([png, svg, ipe])

    assert _representation(manifest, "png") is png
    assert _optional_representation(manifest, None) is None
    with pytest.raises(AssetNotFoundError):
        _representation(manifest, "missing")
    assert _editor_representation(manifest).representation_id == "ipe"
    assert _ipe_source(_manifest([svg, ipe], editor="svg")) is ipe
    with pytest.raises(DataValidationError, match="editable representation"):
        _editor_representation(_manifest([png]))
    with pytest.raises(DataValidationError, match="Ipe source"):
        _ipe_source(_manifest([svg], editor="svg"))

    remote = AssetRepresentation(
        representation_id="remote",
        format=AssetFormat.PNG,
        url="https://example.com/figure.png",
        purpose="reference",
    )
    no_hash = NormalizedAssetInput(representation=remote, content=None)
    assert _versioned_replacement(no_hash, manifest) is no_hash
    hashed = NormalizedAssetInput(
        representation=png.model_copy(update={"content_hash": "a" * 64}),
        content=b"png",
    )
    duplicate = _manifest([_rep("png-aaaaaaaa", AssetFormat.PNG)])
    with pytest.raises(AssetConflictError, match="replacement already exists"):
        _versioned_replacement(hashed, duplicate)


def test_asset_render_merge_and_preference_edges() -> None:
    source = _rep("source", AssetFormat.IPE, purpose="source", editable=True, digest="1" * 64)
    old = _rep(
        "old",
        AssetFormat.PNG,
        stale=True,
        derived_from="source",
        digest="2" * 64,
    )
    manifest = _manifest([source, old], editor="source", render="old")
    rendered = [
        RenderedAsset(format=AssetFormat.PNG, content=b"new", command=("ipe",), metadata={})
    ]
    updated, files, generated = _merge_rendered(manifest, source, rendered)
    assert files and generated
    assert updated.preferred_render == generated[0]
    assert updated.representations[-1].metadata["supersedes"] == "old"

    same_digest = updated.representations[-1].content_hash
    assert same_digest is not None
    existing = updated.model_copy(
        update={
            "representations": [
                item.model_copy(update={"stale": True})
                if item.representation_id == generated[0]
                else item
                for item in updated.representations
            ]
        }
    )
    reused, reused_files, reused_ids = _merge_rendered(existing, source, rendered)
    assert reused_files == {}
    assert reused_ids == generated
    assert not _representation(reused, generated[0]).stale

    active = _manifest([source, old.model_copy(update={"stale": False})], render="old")
    assert _render_preference(active, active.representations, []) == "old"
    assert _render_preference(manifest, manifest.representations, []) == "old"


def test_asset_edit_reconcile_and_restore_parent_edges() -> None:
    base = _rep("base", AssetFormat.IPE, purpose="source", editable=True, digest="1" * 64)
    edit1 = _rep(
        "base-edit-1",
        AssetFormat.IPE,
        purpose="source",
        editable=True,
        derived_from="base",
        digest="2" * 64,
    )
    render1 = _rep(
        "render-1",
        AssetFormat.PNG,
        derived_from="base",
        digest="3" * 64,
    )
    render2 = _rep(
        "render-2",
        AssetFormat.PNG,
        derived_from="base-edit-1",
        digest="4" * 64,
        metadata={"supersedes": "render-1"},
    )
    manifest = _manifest([base, edit1, render1, render2], editor="base-edit-1", render="render-2")
    assert _next_edit_identifier(manifest, "base") == "base-edit-2"
    reconciled = _reconciled_editor_manifest(manifest, edit1, "f" * 64)
    assert _representation(reconciled, "base-edit-1").metadata["previous_content_hash"]
    assert _representation(reconciled, "render-2").stale
    restored, changes = _restored_manifest(manifest)
    assert restored.preferred_editor == "base"
    assert restored.preferred_render == "render-1"
    assert set(changes) == {"preferred_editor", "preferred_render"}

    assert _editable_parent(manifest, None) is None
    assert _editable_parent(manifest, base) is None
    assert _render_parent(manifest, render2, base) is render1
    fallback_manifest = _manifest([base, render1], editor="base", render=None)
    assert _render_parent(fallback_manifest, None, base) is render1
    with pytest.raises(DataValidationError, match="no previous version"):
        _restored_manifest(_manifest([base], editor="base"))


def test_tag_and_saved_view_rejection_edges(project: tuple[Path, Any], make_question: Any) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    add_question_in_context(
        context,
        make_question(id="OPT-EDGE-0001", topics=["alpha", "beta"]),
        services=create_project_services(context).mutations,
    )
    services = create_project_services(context)
    services.tags.normalize(dry_run=False, command="edge normalize")

    assert services.tags.suggestions()
    with pytest.raises(Exception, match="tag not found"):
        services.tags.show_tag("not-registered")
    with pytest.raises(DataValidationError, match="top_n"):
        services.tags.overview(top_n=0)
    with pytest.raises(DataValidationError, match="identical"):
        services.tags.rename("alpha", "alpha", dry_run=True, command="edge")
    with pytest.raises(ConflictError, match="target tag"):
        services.tags.rename("alpha", "beta", dry_run=True, command="edge")
    with pytest.raises(DataValidationError, match="identical"):
        services.tags.merge("alpha", "alpha", dry_run=True, command="edge")
    with pytest.raises(DataValidationError, match="at least one"):
        services.tags.bulk_edit([], dry_run=True, command="edge")
    with pytest.raises(DataValidationError, match="added and removed"):
        services.tags.bulk_edit(
            ["OPT-EDGE-0001"], add=["alpha"], remove=["alpha"], dry_run=True, command="edge"
        )
    registered = services.tags.register_pending(
        ["alpha", "gamma", "gamma"], dry_run=True, command="edge"
    )
    assert {tag.slug for tag in registered.taxonomy_after} >= {"alpha", "gamma"}
    services.tags.normalize(dry_run=True, command="edge normalize again")

    views = services.views
    with pytest.raises(ConflictError, match="built-in"):
        views.save("ALL", QueryFilters(), dry_run=True)
    views.save("custom", QueryFilters(topics=["alpha"]), dry_run=False)
    with pytest.raises(DataValidationError, match="renamed"):
        views.rename("draft", "draft-2", dry_run=True)
    with pytest.raises(ConflictError, match="already exists"):
        views.rename("custom", "all", dry_run=True)
    with pytest.raises(Exception, match="saved view not found"):
        views.resolve("missing")
    unlocked_views = type(views)(
        repository=views.repository,
        store=views.store,
        special=views.special,
        taxonomy=views.taxonomy,
    )
    unlocked_views.save("unlocked", QueryFilters(), dry_run=False)


def test_unlocked_application_service_boundaries() -> None:
    calls: list[str] = []
    repository = SimpleNamespace(
        discard_new=lambda _question, _asset: calls.append("discard"),
        record=lambda _event: calls.append("record"),
    )
    assets = AssetApplicationService(
        repository=repository,
        inputs=SimpleNamespace(),
        renderer=SimpleNamespace(),
        launcher=SimpleNamespace(),
    )
    assets.discard_new_asset("Q-1", "figure")
    assets._record_event(
        AssetHistoryEvent(
            operation="asset_open",
            question_id="Q-1",
            asset_id="figure",
            representation_ids=(),
        )
    )
    assert calls == ["discard", "record"]

    child_only = _manifest([_rep("base", AssetFormat.PNG)]).model_copy(
        update={"representations": [_rep("child", AssetFormat.PNG, derived_from="missing")]}
    )
    assets.repository = SimpleNamespace(get=lambda _question, _asset: child_only)
    with pytest.raises(DataValidationError, match="no original reference"):
        assets.open_original("Q-1", "figure", dry_run=True)
    assert PureSuffix.from_path(None) == ""

    snapshot = SimpleNamespace(require_consistent=lambda: calls.append("consistent"))
    question_repository = SimpleNamespace(scan=lambda: snapshot)
    index = SimpleNamespace(
        ensure_searchable=lambda value: calls.append("searchable") if value is snapshot else None,
        query=lambda _filters: [],
        rebuild=lambda value: 7 if value is snapshot else 0,
    )
    questions = QuestionService(
        repository=question_repository,
        validator=SimpleNamespace(),
        index=index,
    )
    assert questions.query_summaries(QueryFilters()) == []
    assert questions.rebuild_index() == 7
    with pytest.raises(RuntimeError, match="mutation service"):
        questions.patch_question("Q-1", QuestionPatch(), dry_run=True)
