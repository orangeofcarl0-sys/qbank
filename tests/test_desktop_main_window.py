"""Integration coverage for the real Studio main-window state machine."""

from __future__ import annotations

import base64
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("PySide6.QtCore")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent, QDesktopServices, QImage
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QToolBar,
)
from pytestqt.qtbot import QtBot

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.legacy_qt.controller import DesktopController
from qbank.legacy_qt.main_window import DesktopMainWindow
from qbank.legacy_qt.preferences_dialog import StudioPreferences, StudioPreferencesDialog
from qbank.legacy_qt.question_dialog import QuestionIdentity, QuestionIdentityDialog
from qbank.models import (
    AssetCapabilities,
    DesktopAssetItem,
    DesktopQuestionListResult,
    QueryFilters,
    Question,
)
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
    assert dialogs[-1] == ("校验通过", "0 个校验错误，2 个提示")
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


def test_main_toolbar_is_compact_and_preferences_apply_immediately(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qbank.legacy_qt.main_window.load_studio_preferences",
        lambda theme: StudioPreferences(theme=theme),
    )
    window, _controller = _window(project, question, qtbot)
    toolbars = {toolbar.objectName(): toolbar for toolbar in window.findChildren(QToolBar)}

    assert set(toolbars) >= {"projectToolbar", "editorToolbar"}
    toolbar_heights = {
        name: (
            toolbars[name].minimumHeight(),
            toolbars[name].height(),
            toolbars[name].maximumHeight(),
        )
        for name in ("projectToolbar", "editorToolbar")
    }
    assert all(
        minimum == height == maximum and height <= 38
        for minimum, height, maximum in toolbar_heights.values()
    ), toolbar_heights
    assert window.language_mode.width() == 124
    assert window.language_mode.accessibleName() == "编辑器语法"
    assert "settings" in window._icon_actions
    assert "theme" not in window._icon_actions
    assert window.project_path.text() == ""
    assert window.validation_state.text() in {"✓", "×"}
    assert window.index_state.text() in {"✓", "△", ""}

    selected = StudioPreferences(
        theme="dark",
        workspace_mode="preview",
        show_detail_drawer=False,
        show_project_path=True,
    )
    saved: list[StudioPreferences] = []
    opened_with: list[StudioPreferences] = []

    def select_preferences(
        current: StudioPreferences,
        parent: object = None,
    ) -> StudioPreferences | None:
        del parent
        opened_with.append(current)
        return selected if len(opened_with) == 1 else None

    monkeypatch.setattr(
        StudioPreferencesDialog,
        "get_preferences",
        select_preferences,
    )
    monkeypatch.setattr("qbank.legacy_qt.main_window.save_studio_preferences", saved.append)

    window._show_preferences()

    assert saved == [selected]
    assert window.theme_name == "dark"
    assert window._workspace_mode == "preview"
    assert not window.workspace.preview.isHidden()
    assert window.workspace.editor.isHidden()
    assert window.drawer.isHidden()
    assert window.project_path.text() == str(project[0])

    window._show_preferences()

    assert opened_with[-1].show_project_path


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
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )
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


def test_real_main_window_saved_views_bulk_tags_and_chart_filter(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("review-view", True),
    )
    window._save_current_view()
    assert "review-view" in {view.name for view in controller.navigation_data().views}

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("renamed-view", True),
    )
    window._rename_view("review-view")
    assert "renamed-view" in {view.name for view in controller.navigation_data().views}
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    window._delete_view("renamed-view")
    assert "renamed-view" not in {view.name for view in controller.navigation_data().views}

    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("bulk-topic", True),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Apply,
    )
    window.navigation.questions.selectAll()
    window._bulk_topics(True)
    assert "bulk-topic" in controller.load_question(question.id).question.topics

    window.drawer.metadata.topics.input.setText("novel-studio-topic")
    window.drawer.metadata.topics.input.returnPressed.emit()
    assert window.dirty
    assert window.save_current()
    pending = controller.services.tags.show_tag("novel-studio-topic")
    assert pending.registered and pending.metadata is not None
    assert pending.metadata.status.value == "pending"

    window._pending_topic_created("interference")
    proposed = "interferometr"
    window.drawer.metadata.topics.set_topics([proposed])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )
    window._pending_topic_created(proposed)
    assert proposed not in window.drawer.metadata.topics.topics()
    window._apply_overview_filter(QueryFilters(topics=["bulk-topic"]))
    assert window.navigation.current_filters().topics == ["bulk-topic"]
    window._tag_metadata_changed()


def test_real_main_window_clear_and_overview_each_refresh_once(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    original = controller.navigation_result
    calls: list[QueryFilters] = []

    def counted_navigation_result(
        *, view: str, search: str = "", filters: QueryFilters | None = None
    ):
        if filters is not None:
            calls.append(filters)
        return original(view=view, search=search, filters=filters)

    monkeypatch.setattr(controller, "navigation_result", counted_navigation_result)
    window.navigation.set_transient_filters(QueryFilters(topics=["missing-topic"], limit=100_000))
    assert window.navigation.questions.count() == 0
    calls.clear()

    window.navigation.clear_filter.click()

    assert len(calls) == 1
    assert window.navigation.questions.count() == 1
    assert window.navigation.current_filters().topics == []
    assert not window.navigation.clear_filter.isEnabled()
    calls.clear()

    window._apply_overview_filter(QueryFilters(topics=[question.topics[0]], limit=100_000))

    assert len(calls) == 1
    assert window.navigation.current_view() == "all"
    assert window.navigation.current_filters().topics == [question.topics[0]]


def test_rapid_navigation_search_discards_stale_background_result(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    applied: list[int] = []

    def navigation_result(*, view: str, filters: QueryFilters, **_kwargs: object):
        del view
        if filters.text == "old":
            time.sleep(0.05)
            total = 1
        else:
            total = 2
        return DesktopQuestionListResult(rows=[], tags=[], total=total)

    monkeypatch.setattr(controller, "navigation_result", navigation_result)
    monkeypatch.setattr(
        window,
        "_apply_navigation_result",
        lambda result: applied.append(result.total),
    )

    window.navigation.search.setText("old")
    window.navigation.search_timer.stop()
    window._start_navigation_search("old")
    window.navigation.search.setText("new")
    window.navigation.search_timer.stop()
    window._start_navigation_search("new")

    qtbot.waitUntil(lambda: applied == [2], timeout=5000)
    assert 1 not in applied
    window.close()


def test_main_window_new_and_copy_question_use_visible_repository_workflow(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    monkeypatch.setattr(
        QuestionIdentityDialog,
        "get_new_question",
        lambda *_args, **_kwargs: QuestionIdentity("UI-NEW-0001", "UI new question"),
    )

    window._new_question()

    assert window.current_id == "UI-NEW-0001"
    assert controller.load_question("UI-NEW-0001").question.title == "UI new question"
    monkeypatch.setattr(
        QuestionIdentityDialog,
        "get_question_copy",
        lambda *_args, **_kwargs: QuestionIdentity("UI-COPY-0001"),
    )

    window._copy_current_question()

    copied = controller.load_question("UI-COPY-0001").question
    assert window.current_id == copied.id
    assert copied.status.value == "draft"
    window.close()


def test_question_identity_dialog_validates_once_and_uses_localized_actions(
    qtbot: QtBot,
) -> None:
    dialog = QuestionIdentityDialog("new", "general", "zh-CN")
    qtbot.addWidget(dialog)

    assert not dialog.accept_button.isEnabled()
    assert dialog.accept_button.text() == "创建"
    assert dialog.cancel_button.text() == "取消"
    dialog.form.id_input.setText("bad id")
    assert dialog.form.feedback.objectName() == "statusError"
    dialog.form.id_input.setText("OPT-NEW-0001")
    dialog.form.title_input.setText("新建题目")

    assert dialog.accept_button.isEnabled()
    assert dialog.form.values() == QuestionIdentity("OPT-NEW-0001", "新建题目")
    assert "questions/general/OPT-NEW-0001.md" in dialog.form.target.text()


def test_loaded_question_updates_navigation_membership_immediately(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
) -> None:
    window, _controller = _window(project, question, qtbot)
    window.navigation.set_current_question("NOT-IN-RESULT")
    assert "当前题目不在筛选结果中" in window.navigation.active_filter.text()

    window._load_question(question.id)

    assert "当前题目不在筛选结果中" not in window.navigation.active_filter.text()


def test_paper_menu_disables_context_actions_until_a_paper_is_selected(
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
) -> None:
    window, controller = _window(project, question, qtbot)
    window._refresh_paper_actions()

    assert window._paper_actions["select"].isEnabled()
    assert window._paper_actions["new"].isEnabled()
    assert not window._paper_actions["add"].isEnabled()
    assert not window._paper_actions["validate"].isEnabled()
    assert not window._paper_actions["build"].isEnabled()
    assert not window._paper_actions["export"].isEnabled()

    paper_path = controller.context.paths.papers / "generated" / "ui-paper.yaml"
    controller.create_paper(paper_path, "UI paper", [question.id], dry_run=True)
    controller.create_paper(paper_path, "UI paper", [question.id], dry_run=False)
    window._refresh_paper_state()

    assert all(
        window._paper_actions[key].isEnabled() for key in ("add", "validate", "build", "export")
    )


def test_main_window_project_import_delete_and_paper_failure_paths(  # noqa: PLR0915
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    window, controller = _window(project, question, qtbot)
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", lambda error: errors.append(str(error)))

    monkeypatch.setattr(window, "_can_leave_current", lambda: False)
    window._open_project()
    monkeypatch.setattr(window, "_can_leave_current", lambda: True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: "")
    window._open_project()
    invalid_project = tmp_path / "not-a-bank"
    invalid_project.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(invalid_project))
    window._open_project()
    assert errors

    monkeypatch.setattr(QuestionIdentityDialog, "get_new_question", lambda *_args: None)
    window._new_question()
    monkeypatch.setattr(
        QuestionIdentityDialog,
        "get_new_question",
        lambda *_args: QuestionIdentity("BROKEN-NEW-0001", "Broken"),
    )
    monkeypatch.setattr(
        controller,
        "create_question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("create failed")),
    )
    window._new_question()

    current = window.current_id
    window.current_id = None
    window._copy_current_question()
    window.current_id = current
    monkeypatch.setattr(
        controller,
        "load_question",
        lambda *_args: (_ for _ in ()).throw(ValueError("load failed")),
    )
    window._copy_current_question()
    monkeypatch.undo()
    monkeypatch.setattr(window, "_show_error", lambda error: errors.append(str(error)))

    exchange = tmp_path / "questions.json"
    exchange.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: ("", ""))
    window._import_questions()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(exchange), ""),
    )
    monkeypatch.setattr(
        controller,
        "import_questions",
        lambda *_args, **_kwargs: SimpleNamespace(ok=False, would_write=0),
    )
    window._import_questions()
    assert "无效" in errors[-1]

    window.current_id = None
    window._delete_current_question()
    window.current_id = question.id
    monkeypatch.setattr(window, "_can_leave_current", lambda: True)
    monkeypatch.setattr(
        controller,
        "delete_question",
        lambda *_args, **_kwargs: SimpleNamespace(id=question.id, path="questions/x.md"),
    )
    monkeypatch.setattr(
        window,
        "_message_box",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )
    window._delete_current_question()

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: ("", ""))
    window._select_paper()
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args: (str(tmp_path / "missing.yaml"), ""),
    )
    window._select_paper()
    assert errors

    window.current_id = None
    monkeypatch.setattr(window.navigation, "selected_question_ids", lambda: [])
    window._new_paper()
    window._add_to_paper()
    window.current_id = question.id
    answers = iter((("", False), ("Paper", True), ("", False)))
    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: next(answers))
    window._new_paper()
    window._new_paper()
    monkeypatch.setattr(
        controller,
        "add_to_current_paper",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("paper add failed")),
    )
    window._add_to_paper()

    monkeypatch.setattr(
        controller,
        "validate_current_paper",
        lambda: (_ for _ in ()).throw(ValueError("paper validate failed")),
    )
    window._validate_paper()
    monkeypatch.setattr(
        controller,
        "build_current_paper",
        lambda *_args: (_ for _ in ()).throw(ValueError("paper build failed")),
    )
    window._run_paper_build(tmp_path / "paper.unknown")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: ("", ""))
    window._export_paper()
    assert any("paper" in item for item in errors)


def test_main_window_navigation_view_validation_and_close_edge_paths(  # noqa: PLR0915
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, controller = _window(project, question, qtbot)
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", lambda error: errors.append(str(error)))

    monkeypatch.setattr(
        controller,
        "navigation_result",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("bad filter")),
    )
    window._refresh_navigation()
    window.navigation.search.clear()
    window._start_navigation_search("")
    generation = window._search_generation
    window._apply_navigation_search(generation - 1, None, "stale")
    window._apply_navigation_search(generation, None, "offline")
    window._apply_navigation_search(generation, object(), None)

    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("", False))
    window._save_current_view()
    window._rename_view("all")
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )
    window._delete_view("missing")
    monkeypatch.setattr(window.navigation, "selected_question_ids", lambda: [])
    window._bulk_topics(True)
    monkeypatch.setattr(window.navigation, "selected_question_ids", lambda: [question.id])
    window._bulk_topics(False)

    window._apply_overview_filter(object())
    window.current_id = question.id
    monkeypatch.setattr(
        controller,
        "load_question",
        lambda *_args: (_ for _ in ()).throw(ValueError("question unavailable")),
    )
    window._load_question(question.id)
    assert errors[-1] == "question unavailable"

    window.current_id = None
    window.validate_current()
    assert window.save_current()
    window.current_id = question.id
    monkeypatch.setattr(
        controller,
        "validate_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("validation failed")),
    )
    window.validate_current()
    monkeypatch.setattr(
        controller,
        "save_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("save failed")),
    )
    assert not window.save_current()

    window.dirty = True
    choices = iter(
        (
            QMessageBox.StandardButton.Save,
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Discard,
        )
    )
    monkeypatch.setattr(window, "_message_box", lambda *_args, **_kwargs: next(choices))
    monkeypatch.setattr(window, "save_current", lambda: False)
    assert not window._can_leave_current()
    assert not window._can_leave_current()
    assert window._can_leave_current()

    close = QCloseEvent()
    window.dirty = True
    monkeypatch.setattr(window, "_can_leave_current", lambda: False)
    window.closeEvent(close)
    assert not close.isAccepted()


def test_main_window_remaining_editor_and_dialog_decisions(  # noqa: PLR0915
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
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    window.current_source = ""
    window._editor_ready()
    window.current_source = "source"
    window._editor_ready()
    window._switching = True
    window._source_changed("changed")
    window._metadata_changed()
    window._switching = False
    window.current_id = None
    window._metadata_changed()
    window._render_scheduled_preview()
    window.current_id = question.id

    with monkeypatch.context() as patch:
        patch.setattr(StudioPreferencesDialog, "get_preferences", lambda *_args: None)
        window._show_preferences()
        selected = StudioPreferences(
            theme="dark",
            workspace_mode="preview",
            show_detail_drawer=False,
            show_project_path=True,
        )
        patch.setattr(StudioPreferencesDialog, "get_preferences", lambda *_args: selected)
        patch.setattr("qbank.legacy_qt.main_window.save_studio_preferences", lambda _value: None)
        window._show_preferences()
        assert window.theme_name == "dark" and not window.drawer.isVisible()

    exchange = tmp_path / "questions.json"
    exchange.write_text("[]", encoding="utf-8")
    import_calls: list[bool] = []
    with monkeypatch.context() as patch:
        patch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(exchange), ""))
        patch.setattr(
            controller,
            "import_questions",
            lambda *_args, dry_run, **_kwargs: (
                import_calls.append(dry_run) or SimpleNamespace(ok=True, would_write=1)
            ),
        )
        patch.setattr(
            window,
            "_message_box",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Apply,
        )
        patch.setattr(window, "_refresh_after_question_write", lambda _value: None)
        window._import_questions()
    assert import_calls == [True, False]

    delete_calls: list[bool] = []
    with monkeypatch.context() as patch:
        patch.setattr(window, "_can_leave_current", lambda: True)
        patch.setattr(
            controller,
            "delete_question",
            lambda *_args, dry_run, **_kwargs: (
                delete_calls.append(dry_run)
                or SimpleNamespace(id=question.id, path="questions/q.md")
            ),
        )
        patch.setattr(
            window,
            "_message_box",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        patch.setattr(window, "_refresh_after_question_write", lambda _value: None)
        window._delete_current_question()
    assert delete_calls == [True, False]
    window.current_id = question.id

    paper_calls: list[bool] = []
    answers = iter((("Paper", True), ("edge.yaml", True)))
    with monkeypatch.context() as patch:
        patch.setattr(window.navigation, "selected_question_ids", lambda: [question.id])
        patch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: next(answers))
        patch.setattr(
            controller,
            "create_paper",
            lambda *_args, dry_run, **_kwargs: paper_calls.append(dry_run),
        )
        patch.setattr(window, "_refresh_paper_state", lambda: None)
        patch.setattr(window, "_refresh_navigation", lambda *_args: None)
        window._new_paper()
    assert paper_calls == [True, False]

    changes = [SimpleNamespace(id=f"Q-{index}", before=["a"], after=["b"]) for index in range(9)]
    bulk_calls: list[bool] = []
    with monkeypatch.context() as patch:
        patch.setattr(window.navigation, "selected_question_ids", lambda: [question.id])
        patch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("topic", True))
        patch.setattr(
            controller,
            "bulk_edit_topics",
            lambda *_args, dry_run, **_kwargs: (
                bulk_calls.append(dry_run) or SimpleNamespace(changes=changes, affected_questions=9)
            ),
        )
        patch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Apply,
        )
        patch.setattr(window, "_refresh_navigation_data", lambda: None)
        patch.setattr(window, "_refresh_navigation", lambda *_args: None)
        patch.setattr(window, "_load_question", lambda _value: None)
        window._bulk_topics(True)
    assert bulk_calls == [True, False]

    with monkeypatch.context() as patch:
        patch.setattr(
            controller,
            "possible_tag_synonyms",
            lambda _slug: [SimpleNamespace(slug="similar")],
        )
        discarded: list[str] = []
        patch.setattr(window.drawer.metadata.topics, "discard_topic", discarded.append)
        patch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )
        window._pending_topic_created("new-topic")
        assert discarded == ["new-topic"]
        patch.setattr(controller, "possible_tag_synonyms", lambda _slug: [])
        window._pending_topic_created("unique-topic")

    window._show_validation(SimpleNamespace(ok=True, validation_errors=[], validation_warnings=[]))
    window._show_validation(
        SimpleNamespace(
            ok=False,
            validation_errors=[SimpleNamespace(message="invalid")],
            validation_warnings=[],
        )
    )
    window.current_id = None
    window._asset_action("figure", "open")
    window._legacy_asset_action("assets/a.png", "open")
    window._add_asset_from_file()


def test_main_window_remaining_control_flow_edges(  # noqa: PLR0915
    project: tuple[Path, Any],
    question: Question,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    window, controller = _window(project, question, qtbot)
    monkeypatch.setattr(window, "_show_error", lambda _error: None)
    monkeypatch.setattr(
        window,
        "_message_box",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok,
    )

    editor = QLineEdit()
    qtbot.addWidget(editor)
    editor.show()
    editor.setFocus()
    editor.setText("before")
    editor.insert("-after")
    QApplication.processEvents()
    window._undo_current_focus()
    window._redo_current_focus()

    with monkeypatch.context() as patch:
        patch.setattr(QuestionIdentityDialog, "get_question_copy", lambda *_args: None)
        window._copy_current_question()

    exchange = tmp_path / "questions.json"
    exchange.write_text("[]", encoding="utf-8")
    with monkeypatch.context() as patch:
        patch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(exchange), ""))
        patch.setattr(
            controller,
            "import_questions",
            lambda *_args, **_kwargs: SimpleNamespace(ok=True, would_write=1),
        )
        patch.setattr(
            window,
            "_message_box",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )
        window._import_questions()

    loaded: list[str] = []
    with monkeypatch.context() as patch:
        patch.setattr(window, "_refresh_navigation_data", lambda: None)
        patch.setattr(window, "_refresh_navigation", lambda *_args: None)
        patch.setattr(window, "_refresh_project_state", lambda: None)
        patch.setattr(window, "_load_question", loaded.append)
        window._refresh_after_question_write(None)
        window._refresh_after_question_write(question.id)
    assert loaded == [question.id]

    built: list[Path | None] = []
    with monkeypatch.context() as patch:
        output = tmp_path / "paper.html"
        patch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(output), ""))
        patch.setattr(window, "_run_paper_build", lambda output: built.append(output))
        window._export_paper()
    assert built == [output]

    changes = [SimpleNamespace(id="Q-1", before=["a"], after=["b"])]
    with monkeypatch.context() as patch:
        patch.setattr(window.navigation, "selected_question_ids", lambda: [question.id])
        patch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("topic", True))
        patch.setattr(
            controller,
            "bulk_edit_topics",
            lambda *_args, **_kwargs: SimpleNamespace(changes=changes, affected_questions=1),
        )
        patch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )
        window._bulk_topics(False)

    with monkeypatch.context() as patch:
        patch.setattr(
            controller,
            "possible_tag_synonyms",
            lambda _slug: [SimpleNamespace(slug="similar")],
        )
        patch.setattr(
            QMessageBox,
            "question",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window._pending_topic_created("new-topic")

    window.current_id = None
    window._tag_metadata_changed()
    window.current_id = question.id
    with monkeypatch.context() as patch:
        patch.setattr(window, "_can_leave_current", lambda: False)
        refreshed: list[bool] = []
        patch.setattr(window, "_refresh_navigation", lambda *_args: refreshed.append(True))
        window._select_question("other")
        assert refreshed

    with monkeypatch.context() as patch:
        patch.setattr(
            controller,
            "save_source",
            lambda *_args, **_kwargs: SimpleNamespace(
                ok=False,
                validation_errors=[SimpleNamespace(message="bad")],
                validation_warnings=[],
                warnings=[],
            ),
        )
        assert not window.save_current()

    window._preview_loading = True
    window._asset_action("figure", "open")
    window._preview_loading = False
    window._asset_action("figure", "unsupported")
