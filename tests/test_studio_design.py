"""Focused regression tests for Studio design and interaction contracts."""

# GUI modules are imported only after optional-dependency skip checks.

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractSpinBox, QListWidget, QToolButton
from pytestqt.qtbot import QtBot

from qbank.desktop.bridges import PreviewBridge
from qbank.desktop.main_window import preview_result_is_current, snapshot_is_dirty
from qbank.desktop.widgets import MetadataPanel, NavigationPane, WebWorkspace
from qbank.models import DesktopQuestionSummary
from qbank.presentation.studio.design.controls import ModernComboBox, ModernSpinBox
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import DARK, LIGHT
from qbank.presentation.studio.design.stylesheet import build_stylesheet
from qbank.presentation.studio.design.web_theme import css_variables, state_page


def test_design_tokens_cover_both_qt_and_web_surfaces() -> None:
    required = {
        "background",
        "surface",
        "surface_elevated",
        "surface_hover",
        "border_subtle",
        "border_strong",
        "text_primary",
        "text_secondary",
        "text_disabled",
        "accent",
        "accent_hover",
        "selection",
        "focus",
        "success",
        "warning",
        "error",
    }
    assert required <= set(LIGHT.__dataclass_fields__)
    assert required <= set(DARK.__dataclass_fields__)
    assert METRICS.radius_small == 4
    assert METRICS.radius_medium == 6
    for theme in ("light", "dark"):
        qss = build_stylesheet(theme)
        css = css_variables(theme)
        assert "QToolBar" in qss
        assert "QComboBox QAbstractItemView" in qss
        assert "QSpinBox { padding-right" in qss
        assert "QComboBox::down-arrow" not in qss
        assert "--qbank-surface-elevated" in css
        assert "--qbank-focus" in css


def test_metadata_panel_uses_stacked_accessible_inspector_fields(qtbot: QtBot) -> None:
    panel = MetadataPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "metadataPanel"
    assert panel.layout().count() >= 24
    for control, label in (
        (panel.title, "标题"),
        (panel.subject, "学科"),
        (panel.chapter, "章节"),
        (panel.topics, "主题"),
        (panel.question_type, "题型"),
        (panel.status, "状态"),
        (panel.difficulty, "难度"),
        (panel.language, "语言"),
    ):
        assert control.accessibleName() == label

    assert isinstance(panel.question_type, ModernComboBox)
    assert isinstance(panel.status, ModernComboBox)
    assert isinstance(panel.difficulty, ModernSpinBox)
    assert panel.difficulty.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons


def test_modern_inspector_controls_paint_and_step_without_win32_button_frames(
    qtbot: QtBot,
) -> None:
    panel = MetadataPanel("light")
    panel.resize(360, 650)
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)

    combo = panel.question_type
    combo.setFocus()
    combo.repaint()
    combo.showPopup()
    qtbot.wait(20)
    combo.hidePopup()

    spin = panel.difficulty
    spin.setValue(2)
    buttons = [
        button
        for button in spin.findChildren(QToolButton)
        if button.objectName() == "spinStepButton"
    ]
    assert [button.accessibleName() for button in buttons] == ["增加数值", "减少数值"]
    qtbot.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
    assert spin.value() == 3
    qtbot.mouseClick(buttons[1], Qt.MouseButton.LeftButton)
    assert spin.value() == 2

    panel.set_theme("dark")
    assert combo.theme_name == "dark"
    assert spin.theme_name == "dark"
    panel.repaint()


def test_navigation_preserves_all_questions_and_clears_presets(qtbot: QtBot) -> None:
    pane = NavigationPane()
    qtbot.addWidget(pane)
    rows = [
        DesktopQuestionSummary(
            id="OPT-INTERF-001",
            title="Michelson 干涉仪的光程差",
            subject="optics",
            question_type="short_answer",
            difficulty=3,
            status="reviewed",
            needs_redraw=False,
        )
    ]
    pane.set_rows(rows, None)
    pane.views.setCurrentRow(2)
    pane.search.setText("干涉")
    assert pane.views.item(0).data(Qt.ItemDataRole.UserRole) == "all"
    assert "搜索“干涉”" in pane.active_filter.text()
    pane.clear_filters()
    assert pane.current_view() == "all"
    assert pane.search.text() == ""
    assert pane.views.count() == 4


def test_preview_bridge_requests_native_menu_coordinates(qtbot: QtBot) -> None:
    bridge = PreviewBridge()
    with qtbot.waitSignal(
        bridge.context_menu_requested,
        timeout=1000,
    ) as emitted:
        bridge.requestContextMenu("diagram", 120, 240)
    assert emitted.args == ["diagram", 120, 240]


def test_filter_refresh_never_auto_selects_a_different_question(qtbot: QtBot) -> None:
    pane = NavigationPane()
    qtbot.addWidget(pane)
    first = DesktopQuestionSummary(
        id="Q-001",
        title="First",
        subject="optics",
        question_type="short_answer",
        difficulty=2,
        status="draft",
        needs_redraw=False,
    )
    second = first.model_copy(update={"id": "Q-002", "title": "Second"})
    emitted: list[str] = []
    pane.question_selected.connect(emitted.append)

    pane.set_rows([first, second], None)
    assert emitted == ["Q-001"]
    emitted.clear()
    pane.set_rows([first], "Q-002")

    assert emitted == []
    assert pane.questions.currentRow() == -1
    pane.set_rows([], "Q-002")
    assert pane.empty_hint.isVisible() is False  # Parent is not shown in this unit test.
    assert not pane.empty_hint.isHidden()


def test_saved_snapshot_and_preview_generation_contracts() -> None:
    saved = {"title": "Michelson 干涉仪", "difficulty": 3}
    changed = {**saved, "difficulty": 4}
    assert snapshot_is_dirty("source + edit", saved, "source", saved)
    assert snapshot_is_dirty("source", changed, "source", saved)
    assert not snapshot_is_dirty("source", saved, "source", saved)
    assert preview_result_is_current(4, 4, "OPT-001", "OPT-001")
    assert not preview_result_is_current(3, 4, "OPT-001", "OPT-001")
    assert not preview_result_is_current(4, 4, "OPT-001", "OPT-002")


def test_editor_bridge_reports_document_changes_without_debounce() -> None:
    entry = (
        Path(__file__).parents[1] / "src" / "qbank" / "resources" / "desktop" / "editor-entry.js"
    ).read_text(encoding="utf-8")

    assert "bridge.sourceChanged(update.state.doc.toString())" in entry
    assert "setTimeout" not in entry


def test_component_gallery_uses_production_surfaces_and_real_questions(qtbot: QtBot) -> None:
    from qbank.presentation.studio.gallery import StudioGallery

    gallery = StudioGallery("dark")
    qtbot.addWidget(gallery)
    text = "\n".join(
        item.text()
        for widget in gallery.findChildren(QListWidget)
        for index in range(widget.count())
        if (item := widget.item(index)) is not None
    )

    assert gallery.web_workspace.theme_name == "dark"
    assert "OPT-INT-0001" in text
    assert "OPT-DIF-0001" in text
    assert "OPT-INTERF-001" not in text


def test_codemirror_load_resets_history_and_undo_returns_to_saved_source(qtbot: QtBot) -> None:
    workspace = WebWorkspace()
    qtbot.addWidget(workspace)
    with qtbot.waitSignal(workspace.editor_ready, timeout=10_000):
        workspace.show()

    saved = "## Question B\n\nSaved body\n"
    workspace.set_source("## Question A\n")
    workspace.insert_asset("temporary")
    workspace.set_source(saved)
    workspace.undo()

    values: list[object] = []
    workspace.editor.page().runJavaScript("window.qbankEditor.getValue()", values.append)
    qtbot.waitUntil(lambda: bool(values), timeout=5_000)
    assert values == [saved]

    with qtbot.waitSignal(workspace.source_edited, timeout=5_000) as edited:
        workspace.insert_asset("temporary")
    assert snapshot_is_dirty(str(edited.args[0]), {}, saved, {})
    with qtbot.waitSignal(workspace.source_edited, timeout=5_000) as undone:
        workspace.undo()
    assert undone.args == [saved]
    assert not snapshot_is_dirty(str(undone.args[0]), {}, saved, {})


def test_preview_state_pages_escape_content_and_share_theme() -> None:
    page = state_page("dark", "预览错误", "<script>alert(1)</script>", state="error")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert DARK.error in page
    assert "role='alert'" in page
    assert "aria-live='assertive'" in page


def test_studio_has_no_scattered_hex_colors_outside_design_package() -> None:
    root = Path(__file__).parents[1] / "src/qbank"
    paths = [
        root / "desktop/main_window.py",
        root / "desktop/widgets.py",
        root / "resources/desktop/editor.html",
        root / "resources/desktop/preview.html.j2",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"#[0-9a-fA-F]{3,8}\b", text) is None, path
