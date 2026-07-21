"""Reusable Qt Widgets for the lightweight two-and-a-half-column shell."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qbank.desktop.bridges import EditorBridge, PreviewBridge
from qbank.models import (
    DesktopQuestionDocument,
    DesktopQuestionSummary,
    QuestionStatus,
    QuestionType,
)
from qbank.presentation.studio.design.controls import ModernComboBox, ModernSpinBox
from qbank.presentation.studio.design.icons import icon
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.web_theme import css_variables, state_page

WorkspaceMode = Literal["source", "preview", "split"]


class NavigationPane(QWidget):
    """Zotero-style saved views and question navigation."""

    theme_name: ThemeName

    view_changed = Signal(str)
    question_selected = Signal(str)
    search_changed = Signal(str)

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self.setObjectName("navigationPane")
        self.setMinimumWidth(METRICS.nav_width)
        self.setMaximumWidth(METRICS.nav_width + METRICS.space_8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索题目、主题或公式")
        self.search.setAccessibleName("搜索题目")
        self.clear_filter = QToolButton()
        self.clear_filter.setIcon(icon("clear", theme))
        self.clear_filter.setIconSize(QSize(METRICS.icon_small, METRICS.icon_small))
        self.clear_filter.setToolTip("清除搜索和筛选")
        self.clear_filter.setAccessibleName("清除搜索和筛选")
        self.active_filter = QLabel()
        self.active_filter.setObjectName("activeFilter")
        self.views = QListWidget()
        self.views.setAccessibleName("保存的筛选视图")
        self.views.setMaximumHeight(METRICS.control_height * 6)
        self.questions = QListWidget()
        self.questions.setAccessibleName("题目列表")
        self.questions.setAlternatingRowColors(True)
        self.empty_hint = _empty_hint()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 8, 10)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.clear_filter)
        layout.addLayout(search_row)
        layout.addWidget(self.active_filter)
        layout.addWidget(self.views)
        layout.addWidget(QLabel("题目"))
        layout.addWidget(self.empty_hint)
        layout.addWidget(self.questions, 1)
        self._populate_views()
        self.views.setCurrentRow(0)
        self._update_active_filter()
        self._connect_signals()

    def _populate_views(self) -> None:
        for label, value in (
            ("全部题目", "all"),
            ("draft", "draft"),
            ("图形待重绘", "needs_redraw"),
            ("当前试卷", "paper"),
        ):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, value)
            self.views.addItem(item)

    def _connect_signals(self) -> None:
        self.views.currentItemChanged.connect(self._emit_view)
        self.questions.currentItemChanged.connect(self._emit_question)
        self.search.textChanged.connect(self.search_changed.emit)
        self.search.textChanged.connect(self._update_active_filter)
        self.clear_filter.clicked.connect(self.clear_filters)

    def set_rows(self, rows: list[DesktopQuestionSummary], selected: str | None) -> None:
        """Replace question rows while retaining the current logical ID."""
        self.questions.blockSignals(True)
        self.questions.clear()
        selected_row = -1
        for index, row in enumerate(rows):
            item = QListWidgetItem(f"{row.title}\n{row.id}")
            item.setData(Qt.ItemDataRole.UserRole, row.id)
            item.setToolTip(f"{row.subject} · {row.question_type} · 难度 {row.difficulty}")
            if row.needs_redraw:
                item.setIcon(icon("warning", self.theme_name, semantic="warning"))
                item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, "图形需要重绘")
            self.questions.addItem(item)
            if row.id == selected:
                selected_row = index
        if selected_row >= 0:
            self.questions.setCurrentRow(selected_row)
        elif selected is None and rows:
            self.questions.setCurrentRow(0)
        else:
            self.questions.setCurrentRow(-1)
        self.questions.blockSignals(False)
        self.empty_hint.setVisible(not rows)
        if selected is None and rows:
            self.question_selected.emit(rows[0].id)

    def current_view(self) -> str:
        """Return the selected saved-view identifier."""
        item = self.views.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole))

    def clear_filters(self) -> None:
        """Restore the stable all-questions view and clear free-text search."""
        self.search.clear()
        self.views.setCurrentRow(0)
        self._update_active_filter()

    def set_theme(self, theme: ThemeName) -> None:
        """Refresh theme-dependent icons without rebuilding navigation."""
        self.theme_name = theme
        self.clear_filter.setIcon(icon("clear", theme))

    def _update_active_filter(self, *_: object) -> None:
        item = self.views.currentItem()
        label = item.text()
        query = self.search.text().strip()
        suffix = f" · 搜索“{query}”" if query else ""
        self.active_filter.setText(f"当前筛选：{label}{suffix}")
        self.clear_filter.setEnabled(bool(query) or self.current_view() != "all")

    def _emit_view(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is not None:
            self._update_active_filter()
            self.view_changed.emit(str(current.data(Qt.ItemDataRole.UserRole)))

    def _emit_question(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is not None:
            self.question_selected.emit(str(current.data(Qt.ItemDataRole.UserRole)))


class MetadataPanel(QWidget):
    """Compact basic properties kept outside the primary writing area."""

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self.setObjectName("metadataPanel")
        self.title = QLineEdit()
        self.subject = QLineEdit()
        self.chapter = QLineEdit()
        self.topics = QLineEdit()
        self.question_type = ModernComboBox(theme)
        self.question_type.addItems([item.value for item in QuestionType])
        self.status = ModernComboBox(theme)
        self.status.addItems([item.value for item in QuestionStatus])
        self.difficulty = ModernSpinBox(theme)
        self.difficulty.setRange(1, 5)
        self.language = QLineEdit()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_3,
            METRICS.space_3,
            METRICS.space_3,
            METRICS.space_4,
        )
        layout.setSpacing(0)
        for label_text, control in (
            ("标题", self.title),
            ("学科", self.subject),
            ("章节", self.chapter),
            ("主题", self.topics),
            ("题型", self.question_type),
            ("状态", self.status),
            ("难度", self.difficulty),
            ("语言", self.language),
        ):
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            label.setBuddy(control)
            control.setAccessibleName(label_text)
            layout.addWidget(label)
            layout.addSpacing(METRICS.space_1)
            layout.addWidget(control)
            layout.addSpacing(METRICS.space_2)
        layout.addStretch()

    def set_theme(self, theme: ThemeName) -> None:
        """Refresh the custom inspector controls for a theme change."""
        self.theme_name = theme
        self.question_type.set_theme(theme)
        self.status.set_theme(theme)
        self.difficulty.set_theme(theme)

    def load_document(self, document: DesktopQuestionDocument) -> None:
        """Populate controls from one question model."""
        question = document.question
        self.title.setText(question.title)
        self.subject.setText(question.subject)
        self.chapter.setText(question.chapter or "")
        self.topics.setText(", ".join(question.topics))
        self.question_type.setCurrentText(question.type.value)
        self.status.setCurrentText(question.status.value)
        self.difficulty.setValue(question.difficulty)
        self.language.setText(question.language)

    def values(self) -> dict[str, object]:
        """Return typed values accepted by the question patch model."""
        return {
            "title": self.title.text(),
            "subject": self.subject.text(),
            "chapter": self.chapter.text(),
            "topics": self.topics.text(),
            "type": self.question_type.currentText(),
            "status": self.status.currentText(),
            "difficulty": self.difficulty.value(),
            "language": self.language.text(),
        }


class DetailDrawer(QDockWidget):
    """Collapsible properties, assets, provenance, and history drawer."""

    asset_activated = Signal(str)

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__("题目详情")
        self.setObjectName("detailDrawer")
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        tabs = QTabWidget()
        self.metadata = MetadataPanel(theme)
        self.assets = QListWidget()
        self.assets.setAccessibleName("图形资产列表")
        self.source = QPlainTextEdit()
        self.source.setAccessibleName("来源信息")
        self.source.setReadOnly(True)
        self.history = QListWidget()
        self.history.setAccessibleName("修改历史")
        tabs.addTab(self.metadata, "基础属性")
        tabs.addTab(_padded(self.assets), "图形资产")
        tabs.addTab(_padded(self.source), "来源")
        tabs.addTab(_padded(self.history), "历史")
        self.setWidget(tabs)
        self.setMinimumWidth(METRICS.nav_width + METRICS.space_8)
        self.assets.itemDoubleClicked.connect(self._activate_asset)
        self.assets.itemActivated.connect(self._activate_asset)

    def set_theme(self, theme: ThemeName) -> None:
        """Refresh theme-dependent controls in every drawer tab."""
        self.metadata.set_theme(theme)

    def load_document(self, document: DesktopQuestionDocument) -> None:
        """Refresh every drawer tab."""
        self.metadata.load_document(document)
        self.assets.clear()
        for asset in document.assets:
            stale = [item.representation_id for item in asset.representations if item.stale]
            text = (
                f"{asset.asset_id}\n{asset.status.value} · "
                f"{len(asset.representations)} representations"
            )
            if stale:
                text += f" · stale {len(stale)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, asset.asset_id)
            item.setToolTip(
                f"editor: {asset.preferred_editor or '—'}\nrender: {asset.preferred_render or '—'}"
            )
            self.assets.addItem(item)
        self.source.setPlainText(
            json.dumps(
                document.question.source.model_dump(mode="json"), ensure_ascii=False, indent=2
            )
        )
        self.history.clear()
        for event in reversed(document.history):
            self.history.addItem(f"{event.timestamp}\n{event.operation} · {event.asset_id}")

    def _activate_asset(self, item: QListWidgetItem) -> None:
        self.asset_activated.emit(str(item.data(Qt.ItemDataRole.UserRole)))


class WebWorkspace(QSplitter):
    """CodeMirror source and interactive QWebEngine preview workspace."""

    theme_name: ThemeName

    source_edited = Signal(str)
    editor_ready = Signal()
    asset_action = Signal(str, str)
    asset_dropped = Signal(str, str, str)
    context_menu_requested = Signal(str, int, int)
    mode_changed = Signal(str)

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.theme_name = theme
        self.asset_actions_enabled = False
        self._expected_preview_question_id: str | None = None
        self.editor = QWebEngineView()
        self.editor.setAccessibleName("Markdown 和 TeX 源码编辑器")
        self.preview = QWebEngineView()
        self.preview.setAccessibleName("题目预览")
        self.editor_bridge = EditorBridge()
        self.preview_bridge = PreviewBridge()
        self._wire_channels()
        self._configure_web_settings()
        self.addWidget(self.editor)
        self.addWidget(self.preview)
        self.setStretchFactor(0, 1)
        self.setStretchFactor(1, 1)
        self.setSizes([680, 680])
        resource = Path(__file__).parents[1] / "resources" / "desktop" / "editor.html"
        self.editor.loadFinished.connect(self._editor_loaded)
        self.preview.loadFinished.connect(self._preview_loaded)
        self.editor.load(QUrl.fromLocalFile(str(resource)))

    def set_source(self, source: str) -> None:
        """Replace the CodeMirror document using JSON-safe JavaScript."""
        encoded = json.dumps(source, ensure_ascii=False)
        self.editor.page().runJavaScript(f"window.qbankEditor?.setValue({encoded});")

    def set_preview(self, html: str, root: Path, question_id: str) -> None:
        """Load an interactive preview with project-relative local assets."""
        base = QUrl.fromLocalFile(str(root.resolve()) + "/")
        self._expected_preview_question_id = question_id
        self.set_asset_actions_enabled(False)
        self.preview.setHtml(html, base)

    def show_loading(self, question_id: str) -> None:
        """Hide stale content immediately while the selected question renders."""
        self._expected_preview_question_id = None
        self.set_asset_actions_enabled(False)
        self.preview.setHtml(
            state_page(self.theme_name, "正在生成预览", f"正在加载 {question_id}…"),
        )

    def show_error(self, message: str) -> None:
        """Replace preview content with a themed, escaped error state."""
        self._expected_preview_question_id = None
        self.set_asset_actions_enabled(False)
        self.preview.setHtml(state_page(self.theme_name, "预览错误", message, state="error"))

    def set_asset_actions_enabled(self, enabled: bool) -> None:
        """Enable native image actions only for the current rendered document."""
        self.asset_actions_enabled = enabled
        value = "true" if enabled else "false"
        self.preview.page().runJavaScript(f"window.qbankAssetActionsEnabled = {value};")

    def set_mode(self, mode: WorkspaceMode) -> None:
        """Show source, preview, or both without destroying either web view."""
        self.editor.setVisible(mode in {"source", "split"})
        self.preview.setVisible(mode in {"preview", "split"})
        self.mode_changed.emit(mode)

    def set_theme(self, theme: ThemeName) -> None:
        """Apply semantic web tokens to the editor; preview updates on render."""
        self.theme_name = theme
        self._apply_editor_theme()

    def set_language_mode(self, mode: str) -> None:
        """Switch CodeMirror syntax highlighting between Markdown and TeX."""
        self.editor.page().runJavaScript(f"window.qbankEditor?.setMode({json.dumps(mode)});")

    def undo(self) -> None:
        """Undo inside CodeMirror."""
        self.editor.page().runJavaScript("window.qbankEditor?.undo();")

    def redo(self) -> None:
        """Redo inside CodeMirror."""
        self.editor.page().runJavaScript("window.qbankEditor?.redo();")

    def insert_asset(self, asset_id: str) -> None:
        """Insert one stable Markdown logical-asset reference at the cursor."""
        self.editor.page().runJavaScript(
            f"window.qbankEditor?.insertAsset({json.dumps(asset_id)});"
        )

    def _wire_channels(self) -> None:
        editor_channel = QWebChannel(self.editor.page())
        editor_channel.registerObject("editorBridge", self.editor_bridge)
        self.editor.page().setWebChannel(editor_channel)
        preview_channel = QWebChannel(self.preview.page())
        preview_channel.registerObject("previewBridge", self.preview_bridge)
        self.preview.page().setWebChannel(preview_channel)
        self.editor_bridge.ready.connect(self.editor_ready.emit)
        self.editor_bridge.source_edited.connect(self.source_edited.emit)
        self.preview_bridge.action_requested.connect(self.asset_action.emit)
        self.preview_bridge.asset_dropped.connect(self.asset_dropped.emit)
        self.preview_bridge.context_menu_requested.connect(self.context_menu_requested.emit)

    def _configure_web_settings(self) -> None:
        for view in (self.editor, self.preview):
            settings = view.settings()
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                True,
            )
            settings.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                True,
            )

    def _editor_loaded(self, ok: bool) -> None:
        if ok:
            self._apply_editor_theme()

    def _preview_loaded(self, ok: bool) -> None:
        if not ok or self._expected_preview_question_id is None:
            return
        expected = self._expected_preview_question_id
        self.preview.page().runJavaScript(
            "document.body?.dataset?.questionId || ''",
            partial(self._enable_matching_preview, expected=expected),
        )

    def _enable_matching_preview(self, value: object, expected: str) -> None:
        if value == expected and self._expected_preview_question_id == expected:
            self.set_asset_actions_enabled(True)

    def _apply_editor_theme(self) -> None:
        css = json.dumps(css_variables(self.theme_name))
        self.editor.page().runJavaScript(
            "const old=document.getElementById('qbank-theme');"
            "if(old)old.remove();"
            "const style=document.createElement('style');"
            "style.id='qbank-theme';"
            f"style.textContent={css};"
            "document.head.appendChild(style);"
        )


def _padded(widget: QWidget) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(7, 7, 7, 7)
    layout.addWidget(widget)
    return wrapper


def _empty_hint() -> QLabel:
    label = QLabel("没有匹配题目。可清除筛选后查看全部题目。")
    label.setObjectName("emptyState")
    label.setWordWrap(True)
    label.setAccessibleName("筛选结果为空")
    label.hide()
    return label
