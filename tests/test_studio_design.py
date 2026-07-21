"""Focused regression tests for Studio design and interaction contracts."""

# GUI modules are imported only after optional-dependency skip checks.

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)
from pytestqt.qtbot import QtBot

from qbank.desktop.bridges import PreviewBridge
from qbank.desktop.main_window import (
    DesktopMainWindow,
    changed_fields_count,
    preview_result_is_current,
    snapshot_is_dirty,
)
from qbank.desktop.widgets import (
    AssetCard,
    DetailDrawer,
    EmptyState,
    LegacyAssetCard,
    MetadataPanel,
    NavigationPane,
    WebWorkspace,
)
from qbank.models import (
    AssetCapabilities,
    AssetHistoryEntry,
    AssetManifest,
    DesktopAssetItem,
    DesktopQuestionDocument,
    DesktopQuestionSummary,
    Diagnostic,
    DiagnosticCode,
    Question,
)
from qbank.presentation.studio.design.controls import ModernComboBox, ModernSpinBox
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import DARK, LIGHT
from qbank.presentation.studio.design.stylesheet import apply_theme, build_stylesheet
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


def test_qt_theme_keeps_a_valid_scalable_point_size(qtbot: QtBot) -> None:
    application = QApplication.instance()
    widget = QWidget()
    qtbot.addWidget(widget)

    for theme in ("light", "dark", "light"):
        apply_theme(application, theme)
        widget.ensurePolished()
        assert application.font().pointSizeF() > 0
        assert application.font().pixelSize() == -1
        assert widget.font().pointSizeF() > 0
        assert widget.font().pixelSize() == -1

    stylesheet = build_stylesheet("light")
    assert "font-size: 13px" not in stylesheet
    assert "font-size: 9pt" in stylesheet


def test_metadata_panel_uses_dense_accessible_inspector_fields(qtbot: QtBot) -> None:
    panel = MetadataPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "metadataPanel"
    assert panel.layout().count() >= 18
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
    assert panel.layout().itemAtPosition(2, 0).widget() is panel.title
    assert panel.layout().itemAtPosition(6, 0).widget() is panel.topics


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


def test_inspector_localizes_machine_values_and_edits_topics(qtbot: QtBot) -> None:
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.load_document(_inspector_document())

    assert panel.subject.text() == "电子学  ·  electronics"
    assert panel.question_type.currentText() == "多选题"
    assert panel.question_type.currentData() == "multiple_choice"
    assert panel.status.currentText() == "已审阅"
    assert panel.language.text() == "简体中文  ·  zh-CN"
    assert panel.difficulty_caption.text() == "1 / 5 · 基础"
    assert panel.values()["subject"] == "electronics"
    assert panel.values()["type"] == "multiple_choice"

    panel.topics.input.setText("feedback")
    qtbot.keyClick(panel.topics.input, Qt.Key.Key_Return)
    assert panel.topics.topics() == ["op-amp", "ideal-model", "feedback"]
    remove = next(
        button
        for button in panel.topics.findChildren(QToolButton)
        if button.text().startswith("feedback")
    )
    qtbot.mouseClick(remove, Qt.MouseButton.LeftButton)
    assert panel.topics.topics() == ["op-amp", "ideal-model"]

    generated = _inspector_document().model_copy(
        update={
            "question": _inspector_document().question.model_copy(
                update={
                    "source": _inspector_document().question.source.model_copy(
                        update={"type": "generated", "reference": "AI draft"}
                    )
                }
            )
        }
    )
    panel.load_document(generated)
    assert not panel.ai_difficulty_hint.isHidden()

    panel.topics.input.setText("pending-topic")
    panel.load_document(_inspector_document())
    assert panel.topics.input.text() == ""


def test_detail_drawer_updates_summary_tabs_dirty_bar_and_width(qtbot: QtBot) -> None:
    application = QApplication.instance()
    original_organization = application.organizationName()
    original_application = application.applicationName()
    application.setOrganizationName("qbank-tests")
    application.setApplicationName("qbank-tests")
    settings = QSettings()
    original = settings.value("studio/detailDrawerWidth")
    settings.setValue("studio/detailDrawerWidth", 355)
    settings.sync()
    drawer = DetailDrawer()
    qtbot.addWidget(drawer)
    document = _inspector_document(with_asset=True, with_history=True)
    drawer.load_document(document)

    assert drawer.preferred_width() == 355
    assert (drawer.minimumWidth(), drawer.maximumWidth()) == (280, 460)
    assert drawer.summary.title.text() == document.question.title
    assert drawer.summary.identifier.text() == document.question.id
    assert drawer.summary.status.text() == "已审阅"
    assert drawer.summary.asset_count.text() == "资产 1"
    assert [drawer.tabs.tabText(index) for index in range(4)] == [
        "基础属性",
        "资产 1",
        "来源",
        "历史 1",
    ]
    assert not drawer.tabs.tabIcon(1).isNull()
    assert drawer.action_bar.isHidden()

    drawer.set_dirty_state(2, preview_pending=True)
    assert not drawer.action_bar.isHidden()
    assert drawer.action_bar.findChild(QLabel, "changeCount").text() == "2 项修改"
    assert "2 项修改尚未保存" in drawer.summary.warning.text()
    assert "预览待刷新" in drawer.summary.warning.text()

    drawer.summary.copy.click()
    assert drawer.summary.question_id == document.question.id
    if original is None:
        settings.remove("studio/detailDrawerWidth")
    else:
        settings.setValue("studio/detailDrawerWidth", original)
    application.setOrganizationName(original_organization)
    application.setApplicationName(original_application)


def test_asset_source_history_and_empty_states_are_actionable(qtbot: QtBot) -> None:
    drawer = DetailDrawer()
    qtbot.addWidget(drawer)
    document = _inspector_document(with_asset=True, with_history=True)
    drawer.load_document(document)

    card = drawer.assets.findChild(AssetCard)
    assert card is not None
    assert card.asset.asset_id == "diagram"
    assert card.representations.isHidden()
    assert {button.text() for button in card.findChildren(QPushButton)} >= {
        "用 Ipe 编辑",
        "替换",
        "重新渲染",
    }
    toggle = next(
        button
        for button in card.findChildren(QToolButton)
        if button.objectName() == "representationToggle"
    )
    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)
    assert not card.representations.isHidden()
    assert drawer.source.fields["type"].text() == "人工录入"
    assert drawer.source.fields["year"].text() == "2025"
    assert drawer.source.fields["number"].text() == "3"
    assert drawer.source.raw.isHidden()
    qtbot.mouseClick(drawer.source.raw_toggle, Qt.MouseButton.LeftButton)
    assert not drawer.source.raw.isHidden()
    assert len(drawer.history.findChildren(QWidget, "timelineRow")) == 1

    empty = _inspector_document(reference=None)
    drawer.load_document(empty)
    assert drawer.assets.findChild(EmptyState) is not None
    assert not drawer.source.missing.isHidden()
    assert drawer.history.findChild(EmptyState) is not None

    legacy = empty.model_copy(
        update={
            "question": empty.question.model_copy(update={"assets": ["assets/images/legacy.png"]}),
            "asset_items": [
                DesktopAssetItem(
                    kind="local",
                    reference="assets/images/legacy.png",
                    display_name="legacy.png",
                    exists=False,
                )
            ],
        }
    )
    drawer.load_document(legacy)
    assert drawer.assets.findChild(LegacyAssetCard) is not None
    assert drawer.tabs.tabText(1) == "资产 1"


def test_inspector_uses_typed_asset_capabilities_and_rejects_invalid_preview(
    qtbot: QtBot,
) -> None:
    drawer = DetailDrawer()
    qtbot.addWidget(drawer)
    source = _inspector_document(with_asset=True)
    manifest = source.assets[0].model_copy(
        update={
            "preferred_editor": None,
            "representations": [
                source.assets[0].representations[1].model_copy(update={"derived_from": None})
            ],
        }
    )
    document = source.model_copy(
        update={
            "assets": [manifest],
            "asset_items": [
                DesktopAssetItem(
                    kind="logical",
                    reference="qbank-asset:diagram",
                    display_name="diagram",
                    asset_id="diagram",
                    manifest=manifest,
                    exists=True,
                    capabilities=AssetCapabilities(replace=True, show_directory=True),
                ),
                DesktopAssetItem(
                    kind="invalid",
                    reference="../outside.png",
                    display_name="outside.png",
                    diagnostic=Diagnostic(
                        code=DiagnosticCode.ASSET_OUTSIDE_ASSETS,
                        message="resource escapes the assets directory",
                    ),
                ),
            ],
        }
    )

    drawer.load_document(document)
    card = drawer.assets.findChild(AssetCard)
    assert card is not None
    actions = {
        str(button.property("assetAction")): button
        for button in card.findChildren(QPushButton)
        if button.property("assetAction")
    }
    assert not actions["edit"].isEnabled()
    assert actions["replace-file"].isEnabled()
    assert not actions["render"].isEnabled()
    assert actions["edit"].toolTip()
    invalid = next(
        item for item in drawer.assets.findChildren(LegacyAssetCard) if item.item.kind == "invalid"
    )
    assert invalid.item.preview_path is None
    assert invalid.findChildren(QPushButton) == []


def test_source_and_history_never_invent_provenance(qtbot: QtBot) -> None:
    drawer = DetailDrawer()
    qtbot.addWidget(drawer)
    document = _inspector_document(reference=None)
    history = [
        AssetHistoryEntry(
            timestamp="2025-07-21T18:30:00+08:00",
            operation="asset_ingest",
            question_id=document.question.id,
            asset_id="diagram",
            representation_ids=[],
        ),
        AssetHistoryEntry(
            timestamp="legacy-time",
            operation="asset_restore",
            question_id=document.question.id,
            asset_id="diagram",
            representation_ids=[],
        ),
    ]
    drawer.load_document(document.model_copy(update={"history": history}))

    assert drawer.source.fields["number"].text() == "未记录"
    assert drawer.source.fields["method"].text() == "未记录"
    timestamps = drawer.history.findChildren(QLabel)
    assert any(label.text().startswith("2025-07-21 10:30:00 UTC") for label in timestamps)
    invalid = next(label for label in timestamps if label.text().startswith("legacy-time"))
    assert invalid.objectName() == "statusWarning"
    assert "原始值" in invalid.toolTip()


@pytest.mark.parametrize(
    ("choice", "save_result", "expected", "save_calls", "load_calls"),
    [
        (QMessageBox.StandardButton.Save, True, True, 1, 0),
        (QMessageBox.StandardButton.Save, False, False, 1, 0),
        (QMessageBox.StandardButton.Discard, True, True, 0, 1),
        (QMessageBox.StandardButton.Cancel, True, False, 0, 0),
    ],
)
def test_dirty_asset_gate_requires_save_discard_or_cancel(
    choice: QMessageBox.StandardButton,
    save_result: bool,
    expected: bool,
    save_calls: int,
    load_calls: int,
) -> None:
    class WindowState:
        dirty = True
        current_id = "Q-001"

        def __init__(self) -> None:
            self.saved = 0
            self.loaded = 0

        def _sync_dirty(self) -> None:
            pass

        def _message_box(self, *args: object) -> QMessageBox.StandardButton:
            del args
            return choice

        def save_current(self) -> bool:
            self.saved += 1
            return save_result

        def _load_question(self, question_id: str) -> None:
            assert question_id == self.current_id
            self.loaded += 1

    state = WindowState()
    result = DesktopMainWindow._prepare_asset_mutation(state)  # type: ignore[arg-type]

    assert result is expected
    assert state.saved == save_calls
    assert state.loaded == load_calls


def test_asset_refresh_preserves_live_metadata_and_updates_history(qtbot: QtBot) -> None:
    drawer = DetailDrawer()
    qtbot.addWidget(drawer)
    document = _inspector_document(with_asset=True)
    drawer.load_document(document)
    drawer.metadata.title.setText("unsaved title")
    updated = document.model_copy(
        update={
            "history": [
                AssetHistoryEntry(
                    timestamp="2025-07-21T10:30:00Z",
                    operation="asset_render",
                    question_id=document.question.id,
                    asset_id="diagram",
                    representation_ids=["render-svg"],
                )
            ]
        }
    )

    drawer.refresh_asset_state(updated)

    assert drawer.metadata.title.text() == "unsaved title"
    assert len(drawer.history.findChildren(QWidget, "timelineRow")) == 1


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
    assert changed_fields_count("source + edit", changed, "source", saved) == 2
    assert changed_fields_count("source", saved, "source", saved) == 0
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


def test_codemirror_theme_switch_replaces_live_web_theme(qtbot: QtBot) -> None:
    workspace = WebWorkspace("light")
    qtbot.addWidget(workspace)
    with qtbot.waitSignal(workspace.editor_ready, timeout=10_000):
        workspace.show()

    def live_theme() -> dict[str, str]:
        values: list[object] = []
        workspace.editor.page().runJavaScript(
            "JSON.stringify({"
            "surface:getComputedStyle(document.documentElement)"
            ".getPropertyValue('--qbank-surface-elevated').trim(),"
            "scheme:getComputedStyle(document.documentElement).colorScheme"
            "})",
            values.append,
        )
        qtbot.waitUntil(lambda: bool(values), timeout=5_000)
        return json.loads(str(values[0]))

    workspace.set_theme("light")
    assert live_theme() == {"surface": LIGHT.surface_elevated, "scheme": "light"}
    workspace.set_theme("dark")
    assert live_theme() == {"surface": DARK.surface_elevated, "scheme": "dark"}
    workspace.set_theme("light")
    assert live_theme() == {"surface": LIGHT.surface_elevated, "scheme": "light"}


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


def _inspector_document(
    *,
    with_asset: bool = False,
    with_history: bool = False,
    reference: str | None = "实验讲义 2025 第 3 题",
) -> DesktopQuestionDocument:
    question = Question.model_validate(
        {
            "schema_version": "1.0",
            "id": "ELEC-AMP-0001",
            "title": "理想运算放大器基本性质",
            "type": "multiple_choice",
            "subject": "electronics",
            "chapter": "amplifiers",
            "topics": ["op-amp", "ideal-model"],
            "difficulty": 1,
            "status": "reviewed",
            "language": "zh-CN",
            "source": {"type": "manual", "reference": reference},
            "assets": ["qbank-asset:diagram"] if with_asset else [],
            "stem_md": "理想运算放大器有哪些基本性质？",
        }
    )
    assets = (
        [
            AssetManifest.model_validate(
                {
                    "schema_version": "1.0",
                    "asset_id": "diagram",
                    "question_id": question.id,
                    "role": "question-figure",
                    "status": "needs_redraw",
                    "preferred_editor": "ipe-source",
                    "preferred_render": "render-svg",
                    "representations": [
                        {
                            "representation_id": "ipe-source",
                            "format": "ipe",
                            "path": "source.ipe",
                            "purpose": "editable-source",
                            "editable": True,
                            "content_hash": "0" * 64,
                        },
                        {
                            "representation_id": "render-svg",
                            "format": "svg",
                            "path": "render.svg",
                            "purpose": "render",
                            "derived_from": "ipe-source",
                            "content_hash": "1" * 64,
                        },
                    ],
                }
            )
        ]
        if with_asset
        else []
    )
    history = (
        [
            AssetHistoryEntry(
                timestamp="2025-07-21T10:30:00Z",
                operation="asset_ingest",
                question_id=question.id,
                asset_id="diagram",
                representation_ids=["ipe-source", "render-svg"],
            )
        ]
        if with_history
        else []
    )
    return DesktopQuestionDocument(
        question=question,
        source="## 题目\n\n理想运算放大器有哪些基本性质？\n",
        assets=assets,
        history=history,
        asset_items=(
            [
                DesktopAssetItem(
                    kind="logical",
                    reference="qbank-asset:diagram",
                    display_name="diagram",
                    asset_id="diagram",
                    manifest=assets[0],
                    exists=True,
                    capabilities=AssetCapabilities(
                        edit=True,
                        replace=True,
                        render=True,
                        set_render=True,
                        open_original=True,
                        show_directory=True,
                        restore=with_history,
                    ),
                )
            ]
            if with_asset
            else []
        ),
    )
