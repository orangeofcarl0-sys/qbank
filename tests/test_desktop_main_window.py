"""Integration coverage for the real Studio main-window state machine."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
from pytestqt.qtbot import QtBot

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.desktop.controller import DesktopController
from qbank.desktop.main_window import DesktopMainWindow
from qbank.models import AssetCapabilities, DesktopAssetItem, Question
from qbank.operations import add_question
from qbank.rendering import RenderService


def _window(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
) -> tuple[DesktopMainWindow, DesktopController]:
    root, config = project
    context = ProjectContext.from_config(root, config)
    local = context.paths.assets / "images" / "local.png"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"local")
    source = question.model_copy(
        update={
            "assets": ["assets/images/local.png"],
            "stem_md": (
                question.stem_md
                + "\n\n![local](assets/images/local.png)"
                + "\n\n![remote](HTTPS://example.com/figure.png)"
            ),
        }
    )
    add_question(context.root, context.config, source)
    controller = DesktopController(
        context,
        create_project_services(context),
        RenderService(context),
    )
    created = controller.create_asset(
        question.id,
        "data:image/png;base64," + base64.b64encode(b"asset").decode(),
        name="diagram.png",
    )
    assert created.asset_id == "diagram"
    window = DesktopMainWindow(controller)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.current_id == question.id, timeout=10_000)
    QApplication.processEvents()
    return window, controller


def test_real_main_window_edit_preview_save_theme_and_navigation(  # noqa: PLR0915
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    dialogs: list[tuple[str, str]] = []

    def message_box(
        title: str,
        text: str,
        *_args: object,
        **_kwargs: object,
    ) -> QMessageBox.StandardButton:
        dialogs.append((title, text))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(window, "_message_box", message_box)
    window._apply_drawer_width()
    window._editor_ready()
    window._language_mode_changed(window.language_mode, 0)
    for mode in ("source", "preview", "split"):
        window._set_workspace_mode(mode)
        window._workspace_mode_changed(mode)

    original = window.current_source
    window._source_changed(original)
    window._source_changed(original + "\nchanged")
    assert window.dirty
    assert window.windowTitle().endswith(" *")
    window._metadata_changed()
    window._render_scheduled_preview()
    window._render_preview(0, question.id)
    window.validate_current()
    assert dialogs[-1][0] == "校验通过"
    assert window.save_current()
    assert not window.dirty
    assert "changed" in controller.load_question(question.id).source

    window.set_theme("dark")
    assert window.theme_name == "dark"
    window._toggle_theme(False)
    assert window.theme_name == "light"
    window._refresh_navigation(object())
    window._select_question(question.id)
    window._switching = True
    window._select_question("ignored")
    window._switching = False
    assert window._can_leave_current()

    workspace_undo: list[bool] = []
    monkeypatch.setattr(window.workspace, "undo", lambda: workspace_undo.append(True))
    monkeypatch.setattr(window.workspace, "redo", lambda: workspace_undo.append(False))
    window.setFocus()
    window._undo_current_focus()
    window._redo_current_focus()
    assert workspace_undo == [True, False]

    event = QEvent(QEvent.Type.EnabledChange)
    window.changeEvent(event)
    close = QCloseEvent()
    window.closeEvent(close)
    assert close.isAccepted()


def test_real_main_window_asset_capabilities_dispatch_and_reference_safety(  # noqa: PLR0915
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", lambda error: errors.append(str(error)))
    monkeypatch.setattr(
        window,
        "_message_box",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    document = controller.load_question(question.id)
    logical = next(item for item in document.asset_items if item.kind == "logical")
    local = next(item for item in document.asset_items if item.kind == "local")
    external = next(item for item in document.asset_items if item.kind == "external")
    assert logical.asset_id is not None

    for action, expected in (
        ("replace-file", True),
        ("replace-clipboard", True),
        ("open-original", True),
        ("show-directory", True),
        ("edit", False),
        ("render", False),
        ("set-render", False),
        ("restore", True),
        ("unknown", False),
    ):
        assert window._asset_action_available(logical.asset_id, action) is expected
    assert not window._asset_action_available("missing", "edit")

    opened: list[str] = []
    monkeypatch.setattr(
        QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toString()) or True,
    )
    window._open_reference_asset(local)
    window._open_reference_asset(external)
    assert len(opened) == 2
    with pytest.raises(ValueError, match="不可打开"):
        window._open_reference_asset(
            DesktopAssetItem(
                kind="invalid",
                reference="../outside.png",
                display_name="outside.png",
            )
        )
    with pytest.raises(ValueError, match="不存在或不在"):
        window._open_reference_asset(
            DesktopAssetItem(
                kind="local",
                reference="assets/missing.png",
                display_name="missing.png",
                capabilities=AssetCapabilities(open_reference=True),
            )
        )

    dispatched: list[str] = []
    monkeypatch.setattr(window, "_begin_edit", lambda *_args: dispatched.append("edit"))
    monkeypatch.setattr(window, "_replace_file", lambda *_args: dispatched.append("file"))
    monkeypatch.setattr(
        window,
        "_replace_clipboard",
        lambda *_args: dispatched.append("clipboard"),
    )
    monkeypatch.setattr(window, "_choose_render", lambda *_args: dispatched.append("choose"))
    monkeypatch.setattr(controller, "open_original", lambda *_args: dispatched.append("open"))
    monkeypatch.setattr(controller, "render_asset", lambda *_args: dispatched.append("render"))
    monkeypatch.setattr(
        controller,
        "show_asset_directory",
        lambda *_args: dispatched.append("directory"),
    )
    monkeypatch.setattr(controller, "restore_asset", lambda *_args: dispatched.append("restore"))
    monkeypatch.setattr(window, "_refresh_after_asset_change", lambda: dispatched.append("refresh"))
    for action in (
        "edit",
        "replace-file",
        "replace-clipboard",
        "open-original",
        "render",
        "set-render",
        "show-directory",
        "restore",
    ):
        window._dispatch_asset_action(question.id, logical.asset_id, action)
    assert dispatched == [
        "edit",
        "file",
        "clipboard",
        "open",
        "render",
        "refresh",
        "choose",
        "directory",
        "restore",
        "refresh",
    ]

    window._preview_loading = True
    window._asset_action(logical.asset_id, "edit")
    window._preview_loading = False
    window._asset_action(logical.asset_id, "invalid")
    window._legacy_asset_action("missing", "open")
    window._legacy_asset_action(local.reference, "invalid")
    assert errors

    window.workspace.asset_actions_enabled = True
    window._show_asset_context_menu(logical.asset_id, 2, 2)
    assert window._asset_menu is not None
    window._dismiss_asset_menu()
    window._clear_asset_menu()
    window._preview_loading = True
    window._show_asset_context_menu(logical.asset_id, 2, 2)
    assert window._asset_menu is None


def test_real_main_window_file_clipboard_drop_refresh_and_error_paths(  # noqa: PLR0915
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    window, controller = _window(project, question, qtbot)
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", lambda error: errors.append(str(error)))
    monkeypatch.setattr(
        window,
        "_message_box",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    document = controller.load_question(question.id)
    logical = next(item for item in document.asset_items if item.kind == "logical")
    assert logical.asset_id is not None

    source_file = tmp_path / "replacement.png"
    source_file.write_bytes(b"replacement")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    window._add_asset_from_file()
    window._replace_file(question.id, logical.asset_id)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(source_file), ""),
    )
    window._add_asset_from_file()
    window._replace_file(question.id, logical.asset_id)

    QApplication.clipboard().clear()
    with pytest.raises(ValueError, match="剪贴板中没有图片"):
        window._replace_clipboard(question.id, logical.asset_id)
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    QApplication.clipboard().setImage(image)
    window._replace_clipboard(question.id, logical.asset_id)

    manifest = window._manifest(logical.asset_id)
    assert manifest.asset_id == logical.asset_id
    with pytest.raises(ValueError, match="资产不存在"):
        window._manifest("missing")
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *_args, **_kwargs: (manifest.preferred_render or "desktop-source", True),
    )
    window._choose_render(question.id, logical.asset_id)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *_args, **_kwargs: ("", False))
    window._choose_render(question.id, logical.asset_id)

    window._asset_dropped(
        "",
        "drop.png",
        "data:image/png;base64," + base64.b64encode(b"drop").decode(),
    )
    current = controller.load_question(question.id)
    dropped = next(item for item in current.asset_items if item.asset_id == "drop")
    window._asset_dropped(
        dropped.asset_id or "",
        "drop.png",
        "data:image/png;base64," + base64.b64encode(b"new").decode(),
    )

    window._editing_targets["missing"] = (question.id, logical.asset_id)
    window._reconcile_target("unknown")
    monkeypatch.setattr(controller, "reconcile_asset", lambda *_args: SimpleNamespace(ok=True))
    window._reconcile_target("missing")
    monkeypatch.setattr(
        controller,
        "reconcile_asset",
        lambda *_args: (_ for _ in ()).throw(ValueError("reconcile failed")),
    )
    window._reconcile_target("missing")
    assert errors[-1] == "reconcile failed"

    window._restore_current()
    window.current_id = None
    window._restore_current()
    window._refresh_after_asset_change()
    window._reload_after_question_asset_change()
    assert window._prepare_asset_mutation()
    assert not window._asset_action_available("missing", "edit")
    with pytest.raises(ValueError, match="尚未选择"):
        window._manifest("missing")


def test_real_dirty_asset_gate_preserves_or_restores_editor_state(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    authoritative = window._saved_source
    before = {
        path.relative_to(controller.context.paths.assets): path.read_bytes()
        for path in controller.context.paths.assets.rglob("*")
        if path.is_file()
    }
    choices = iter(
        (
            QMessageBox.StandardButton.Save,
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Discard,
        )
    )
    monkeypatch.setattr(window, "_message_box", lambda *_args, **_kwargs: next(choices))
    monkeypatch.setattr(window, "save_current", lambda: False)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: pytest.fail("file picker must not open after failed save"),
    )

    window._source_changed(authoritative + "\nunsaved")
    window._add_asset_from_file()
    assert window.dirty and window.current_source.endswith("unsaved")
    after_failed_save = {
        path.relative_to(controller.context.paths.assets): path.read_bytes()
        for path in controller.context.paths.assets.rglob("*")
        if path.is_file()
    }
    assert after_failed_save == before

    assert not window._prepare_asset_mutation()
    assert window.dirty and window.current_source.endswith("unsaved")
    assert window._prepare_asset_mutation()
    assert window.current_source == authoritative
    assert not window.dirty
    assert not window.windowTitle().endswith(" *")
