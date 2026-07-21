"""Focused tests for the lightweight desktop editing closure."""

from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from qbank.application.assets import AssetApplicationService
from qbank.assets import stable_legacy_asset_id
from qbank.bootstrap import create_project_services
from qbank.cli import app
from qbank.context import ProjectContext
from qbank.desktop.controller import DesktopController
from qbank.domain import RenderedAsset
from qbank.errors import DataValidationError
from qbank.infrastructure.assets import AssetInputAdapter, FileAssetRepository
from qbank.models import (
    AssetFormat,
    AssetPackage,
    AssetPackageRepresentation,
    AssetStatus,
    PatchQuestionResult,
    Question,
    QuestionPatch,
)
from qbank.operations import add_question
from qbank.rendering import RenderService
from qbank.validation import validate_repository_in_context


class _Renderer:
    def render(
        self,
        source: Path,
        formats: tuple[AssetFormat, ...],
        *,
        execute: bool,
    ) -> tuple[RenderedAsset, ...]:
        del source, execute
        return tuple(
            RenderedAsset(
                format=format_,
                content=f"fresh-{format_.value}".encode(),
                command=("ipe", format_.value),
                metadata={},
            )
            for format_ in formats
        )


class _Launcher:
    def open_file(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        return ("open", str(path), str(execute))

    def open_url(self, url: str, *, execute: bool) -> tuple[str, ...]:
        return ("open-url", url, str(execute))

    def open_directory(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        return ("explorer", str(path), str(execute))

    def edit_file(
        self,
        path: Path,
        format_: AssetFormat,
        *,
        execute: bool,
    ) -> tuple[str, ...]:
        return ("ipe", str(path), format_.value, str(execute))


class _FailingMutation:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate

    def apply_patch(
        self,
        question_id: str,
        patch: QuestionPatch,
        *,
        dry_run: bool,
        command: str,
    ) -> PatchQuestionResult:
        if not dry_run:
            raise RuntimeError("question commit failed")
        return self.delegate.apply_patch(
            question_id,
            patch,
            dry_run=True,
            command=command,
        )


def _context(project: tuple[Path, Any]) -> ProjectContext:
    root, config = project
    return ProjectContext.from_config(root, config)


def _service(context: ProjectContext) -> AssetApplicationService:
    return AssetApplicationService(
        repository=FileAssetRepository(context),
        inputs=AssetInputAdapter(context),
        renderer=_Renderer(),
        launcher=_Launcher(),
    )


def _ipe_package(question_id: str) -> AssetPackage:
    return AssetPackage(
        schema_version="1.0",
        question_id=question_id,
        asset_id="diagram",
        role="diagram",
        representations=[
            AssetPackageRepresentation(
                representation_id="ipe-source",
                format=AssetFormat.IPE,
                base64=base64.b64encode(b"<ipe>original</ipe>").decode(),
                purpose="editable-source",
                editable=True,
            ),
            AssetPackageRepresentation(
                representation_id="render-png",
                format=AssetFormat.PNG,
                base64=base64.b64encode(b"old-render").decode(),
                purpose="render",
                derived_from="ipe-source",
            ),
        ],
        suggested_editor="ipe-source",
        suggested_render="render-png",
        status=AssetStatus.FINAL,
        provenance={"source": "test"},
    )


def test_qbank_asset_and_tex_references_project_to_one_stable_binding(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    context = _context(project)
    service = _service(context)
    service.ingest_package(_ipe_package(question.id), context.root, dry_run=False)
    logical = question.model_copy(
        update={
            "assets": ["qbank-asset:diagram"],
            "stem_md": ("Markdown: ![图](qbank-asset:diagram)\n\nTeX: \\qbankasset{diagram}"),
        }
    )
    add_question(context.root, context.config, logical)

    projected, warnings, bindings = DesktopController(
        context,
        create_project_services(context),
        RenderService(context),
    ).assets.project_question_with_bindings(logical, target="preview")

    assert projected.stem_md.count("assets/") == 2
    assert projected.assets == [f"assets/{question.id}/diagram/render-png.png"]
    assert bindings == {projected.assets[0]: "diagram"}
    assert warnings == []
    assert validate_repository_in_context(context).ok


def test_ipe_working_copy_reconcile_render_and_restore_preserve_versions(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    context = _context(project)
    service = _service(context)
    service.ingest_package(_ipe_package(question.id), context.root, dry_run=False)

    planned = service.begin_edit_session(question.id, "diagram", dry_run=True)
    opened = service.begin_edit_session(question.id, "diagram", dry_run=False)
    assert planned.representation_id == "ipe-source"
    assert opened.representation_id == "ipe-source-edit-1"
    original = service.repository.representation_path(
        service.show_asset(question.id, "diagram").asset,
        "ipe-source",
    )
    assert original is not None and original.read_bytes() == b"<ipe>original</ipe>"

    working = Path(opened.target)
    working.write_bytes(b"<ipe>changed</ipe>")
    service.reconcile_editor_change(question.id, "diagram", dry_run=True)
    service.reconcile_editor_change(question.id, "diagram", dry_run=False)
    reconciled = service.show_asset(question.id, "diagram").asset
    assert reconciled.status == AssetStatus.EDITING
    assert next(
        item for item in reconciled.representations if item.representation_id == "render-png"
    ).stale

    rendered = service.render_asset(
        question.id,
        "diagram",
        formats=(AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG),
        dry_run=False,
    )
    fresh = service.show_asset(question.id, "diagram").asset
    assert len(rendered.generated) == 3
    assert fresh.preferred_render in rendered.generated
    assert not next(
        item for item in fresh.representations if item.representation_id == fresh.preferred_render
    ).stale

    service.restore_previous(question.id, "diagram", dry_run=True)
    service.restore_previous(question.id, "diagram", dry_run=False)
    restored = service.show_asset(question.id, "diagram").asset
    assert restored.preferred_editor == "ipe-source"
    assert restored.preferred_render == "render-png"
    assert original.read_bytes() == b"<ipe>original</ipe>"
    operations = [item.operation for item in service.history(question.id, "diagram").events]
    assert operations[-4:] == [
        "asset_edit_begin",
        "asset_edit_saved",
        "asset_render",
        "asset_restore",
    ]


def test_desktop_controller_live_preview_save_reopen_drop_replace_and_restore(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    context = _context(project)
    assets = _service(context)
    assets.ingest_package(_ipe_package(question.id), context.root, dry_run=False)
    logical = question.model_copy(
        update={
            "assets": ["qbank-asset:diagram"],
            "stem_md": "原题 $x=1$。\n\n![图](qbank-asset:diagram)",
        }
    )
    add_question(context.root, context.config, logical)
    services = create_project_services(context)
    controller = DesktopController(context, services, RenderService(context))

    document = controller.load_question(question.id)
    item = next(item for item in document.asset_items if item.asset_id == "diagram")
    assert item.kind == "logical"
    assert item.capabilities.edit
    assert item.capabilities.render
    assert not item.capabilities.set_render
    assert item.capabilities.open_original
    edited = document.source.replace("$x=1$", "$x=2$")
    preview = controller.preview_source(question.id, edited)
    assert 'data-asset-id="diagram"' in preview.html
    assert "$x=2$" in preview.html
    assert controller.validate_source(question.id, edited).dry_run
    saved = controller.save_source(question.id, edited)
    assert saved.ok and not saved.dry_run
    assert "$x=2$" in controller.load_question(question.id).source

    created = controller.create_asset(
        question.id,
        "data:image/png;base64," + base64.b64encode(b"drop").decode(),
        name="拖入 图片.png",
    )
    assert (
        f"qbank-asset:{created.asset_id}" in controller.load_question(question.id).question.assets
    )
    replacement = controller.replace_asset(
        question.id,
        created.asset_id,
        "data:image/png;base64," + base64.b64encode(b"replacement").decode(),
        name="replacement.png",
    )
    assert replacement.action == "replace"
    controller.restore_asset(question.id, created.asset_id)
    restored = next(
        item
        for item in controller.load_question(question.id).assets
        if item.asset_id == created.asset_id
    )
    assert restored.preferred_render == "desktop-source"


def test_desktop_asset_items_classify_and_contain_every_reference(
    project: tuple[Path, Any],
    question: Question,
    tmp_path: Path,
) -> None:
    context = _context(project)
    local = context.paths.assets / "images" / "local.png"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"png")
    with_assets = question.model_copy(
        update={
            "assets": ["assets/images/local.png"],
            "stem_md": (
                "![local](assets/images/local.png)\n\n![remote](HTTPS://example.com/figure.png)"
            ),
        }
    )
    add_question(context.root, context.config, with_assets)
    controller = DesktopController(
        context,
        create_project_services(context),
        RenderService(context),
    )

    items = controller.load_question(question.id).asset_items
    local_item = next(item for item in items if item.kind == "local")
    external_item = next(item for item in items if item.kind == "external")
    assert local_item.preview_path == str(local.resolve())
    assert local_item.capabilities.open_reference
    assert external_item.reference.startswith("HTTPS://")
    assert external_item.capabilities.convert
    assert external_item.diagnostic is not None

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    escaped = controller._desktop_reference_item(
        question.id,
        "../outside.png",
        True,
        {},
        set(),
    )
    absolute = controller._desktop_reference_item(
        question.id,
        str(outside),
        True,
        {},
        set(),
    )
    assert escaped.kind == absolute.kind == "invalid"
    assert escaped.preview_path is None and absolute.preview_path is None
    assert not escaped.capabilities.open_reference

    link = context.paths.assets / "images" / "escape.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pass
    else:
        symlinked = controller._desktop_reference_item(
            question.id,
            "assets/images/escape.png",
            True,
            {},
            set(),
        )
        assert symlinked.kind == "invalid"
        assert symlinked.preview_path is None


def test_new_asset_rolls_back_when_question_declaration_fails(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    context = _context(project)
    add_question(context.root, context.config, question)
    services = create_project_services(context)
    assert services.questions.mutations is not None
    questions = replace(
        services.questions,
        mutations=_FailingMutation(services.questions.mutations),
    )
    controller = DesktopController(
        context,
        replace(services, questions=questions),
        RenderService(context),
    )

    with pytest.raises(RuntimeError, match="question commit failed"):
        controller.create_asset(
            question.id,
            "data:image/png;base64," + base64.b64encode(b"rollback").decode(),
            name="rollback.png",
        )

    assert not (context.paths.assets / question.id / "rollback").exists()
    assert controller.services.questions.get_question(question.id).assets == []
    assert not controller.services.assets.history(question.id, "rollback").events


def test_asset_rollback_failure_preserves_original_exception(
    project: tuple[Path, Any],
    question: Question,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(project)
    add_question(context.root, context.config, question)
    services = create_project_services(context)
    assert services.questions.mutations is not None
    questions = replace(
        services.questions,
        mutations=_FailingMutation(services.questions.mutations),
    )

    def fail_rollback(_question_id: str, _asset_id: str) -> None:
        raise OSError("rollback unavailable")

    monkeypatch.setattr(services.assets, "discard_new_asset", fail_rollback)
    controller = DesktopController(
        context,
        replace(services, questions=questions),
        RenderService(context),
    )

    with pytest.raises(RuntimeError, match="question commit failed") as caught:
        controller.create_asset(
            question.id,
            "data:image/png;base64," + base64.b64encode(b"rollback").decode(),
            name="rollback.png",
        )

    assert caught.value.__notes__ == ["asset rollback failed: rollback unavailable"]


def test_desktop_resources_embed_codemirror_and_closed_asset_actions() -> None:
    root = Path(__file__).parents[1] / "src/qbank/resources/desktop"
    main_window = (Path(__file__).parents[1] / "src/qbank/desktop/main_window.py").read_text(
        encoding="utf-8"
    )
    bundle = (root / "codemirror.bundle.js").read_text(encoding="utf-8")
    editor = (root / "editor.html").read_text(encoding="utf-8")
    editor_entry = (root / "editor-entry.js").read_text(encoding="utf-8")
    preview = (root / "preview.html.j2").read_text(encoding="utf-8")

    assert len(bundle) > 100_000
    assert "qbankEditor" in bundle
    assert "codemirror.bundle.js" in editor
    for label in (
        "用 Ipe 编辑",
        "替换为本地文件",
        "从剪贴板替换",
        "打开原始参考图",
        "重新渲染",
        "设为首选表示",
        "在资源管理器中显示",
        "恢复上一版本",
    ):
        assert label in main_window
    assert "requestContextMenu" in preview
    assert 'id="asset-menu"' not in preview
    assert "assetDropped" in preview
    assert "qbank-asset:" in editor_entry
    assert "view.setState(editorState(value))" in editor_entry
    assert "bridge.sourceChanged(update.state.doc.toString())" in editor_entry
    assert "window.qbankAssetActionsEnabled = false" in preview
    assert "image.tabIndex = 0" in preview
    assert "event.key === 'ContextMenu'" in preview
    assert ".drop-hint { box-sizing: border-box; display: flex" in preview
    assert "@media (max-width: 520px)" in preview
    assert 'class="drop-hint" role="note"' in preview
    assert "position: fixed" not in preview


def test_legacy_path_preview_gets_stable_id_and_normalizes_on_first_action(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    context = _context(project)
    legacy = context.paths.assets / "images" / "legacy.png"
    legacy.write_bytes(b"legacy")
    raw = "assets/images/legacy.png"
    with_legacy = question.model_copy(
        update={
            "assets": [raw],
            "stem_md": f"![旧图]({raw})",
        }
    )
    add_question(context.root, context.config, with_legacy)
    services = create_project_services(context)
    controller = DesktopController(context, services, RenderService(context))
    document = controller.load_question(question.id)

    preview = controller.preview_source(question.id, document.source)
    pending_id = stable_legacy_asset_id(raw)
    assert f'data-asset-id="{pending_id}"' in preview.html
    assert controller.ensure_logical_asset(question.id, pending_id) == pending_id
    normalized = controller.load_question(question.id)
    assert normalized.question.assets == [f"qbank-asset:{pending_id}"]
    assert f"qbank-asset:{pending_id}" in normalized.source
    assert (context.paths.assets / question.id / pending_id / "asset.yaml").is_file()


def test_desktop_navigation_paper_and_asset_actions_use_application_services(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    context = _context(project)
    assets = _service(context)
    assets.ingest_package(_ipe_package(question.id), context.root, dry_run=False)
    add_question(context.root, context.config, question)
    services = replace(create_project_services(context), assets=assets)
    controller = DesktopController(context, services, RenderService(context))

    assert [item.id for item in controller.list_questions()] == [question.id]
    assert controller.list_questions(view="draft") == []
    assert [item.id for item in controller.list_questions(view="needs_redraw")] == []
    assert [item.id for item in controller.list_questions(search="michelson")] == [question.id]
    assert controller.list_questions(search="不存在") == []

    paper_ids = controller.load_current_paper()
    assert question.id in paper_ids
    assert [item.id for item in controller.list_questions(view="paper")] == [question.id]

    opened = controller.begin_asset_edit(question.id, "diagram")
    assert opened.endswith(".ipe")
    assert controller.reconcile_asset(question.id, "diagram").ok
    rendered = controller.render_asset(question.id, "diagram")
    assert len(rendered.generated) == 3
    assert controller.load_question(question.id).asset_items[0].capabilities.set_render
    controller.open_original(question.id, "diagram")
    controller.show_asset_directory(question.id, "diagram")
    selected = controller.set_preferred_render(
        question.id,
        "diagram",
        rendered.generated[0],
    )
    assert selected.ok
    assert controller.restore_asset(question.id, "diagram").ok


def test_desktop_controller_metadata_collisions_and_invalid_inputs(
    project: tuple[Path, Any],
    question: Question,
    tmp_path: Path,
) -> None:
    context = _context(project)
    add_question(context.root, context.config, question)
    controller = DesktopController(
        context,
        create_project_services(context),
        RenderService(context),
    )
    source = controller.load_question(question.id).source

    updated = controller.save_source(
        question.id,
        source,
        {
            "topics": "one, two",
            "difficulty": "3",
            "chapter": " ",
            "ignored": "value",
        },
    )
    assert updated.ok
    saved = controller.load_question(question.id).question
    assert saved.topics == ["one", "two"]
    assert saved.difficulty == 3
    assert saved.chapter is None

    first = controller.create_asset(
        question.id,
        "data:image/png;base64," + base64.b64encode(b"one").decode(),
        name="same.png",
    )
    second = controller.create_asset(
        question.id,
        "data:image/png;base64," + base64.b64encode(b"two").decode(),
        name="same.png",
    )
    assert (first.asset_id, second.asset_id) == ("same", "same-2")

    with pytest.raises(DataValidationError, match="duplicate_section"):
        controller.validate_source(question.id, source + "\n## 题目\n\n重复")
    with pytest.raises(DataValidationError, match="asset_not_found"):
        controller.ensure_logical_asset(question.id, "unknown")
    with pytest.raises(DataValidationError, match="asset_missing"):
        controller.replace_asset(question.id, first.asset_id, str(tmp_path / "missing.png"))

    with pytest.raises(DataValidationError, match="invalid_resource_uri"):
        controller._legacy_representation("data:image/png;base64,AAAA")


def test_desktop_command_maps_launch_results_and_missing_optional_dependency(
    runner: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qbank.desktop

    monkeypatch.setattr(qbank.desktop, "launch", lambda project=None: 0)
    assert runner.invoke(app, ["desktop"]).exit_code == 0

    monkeypatch.setattr(qbank.desktop, "launch", lambda project=None: 4)
    assert runner.invoke(app, ["desktop"]).exit_code == 4

    def missing(project: Path | None = None) -> int:
        del project
        raise ModuleNotFoundError("No module named PySide6", name="PySide6")

    monkeypatch.setattr(qbank.desktop, "launch", missing)
    result = runner.invoke(app, ["desktop"])
    assert result.exit_code == 7
    assert "install qbank with the 'desktop' extra" in result.stderr
