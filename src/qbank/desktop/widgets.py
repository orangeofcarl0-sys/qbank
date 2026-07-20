"""Reusable Qt Widgets for the lightweight two-and-a-half-column shell."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTabWidget,
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

WorkspaceMode = Literal["source", "preview", "split"]


class NavigationPane(QWidget):
    """Zotero-style saved views and question navigation."""

    view_changed = Signal(str)
    question_selected = Signal(str)
    search_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("navigationPane")
        self.setMinimumWidth(215)
        self.setMaximumWidth(310)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索题目")
        self.views = QListWidget()
        self.views.setMaximumHeight(155)
        self.questions = QListWidget()
        self.questions.setAlternatingRowColors(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 8, 10)
        layout.addWidget(self.search)
        layout.addWidget(self.views)
        layout.addWidget(QLabel("题目"))
        layout.addWidget(self.questions, 1)
        for label, value in (
            ("全部题目", "all"),
            ("draft", "draft"),
            ("图形待重绘", "needs_redraw"),
            ("当前试卷", "paper"),
        ):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, value)
            self.views.addItem(item)
        self.views.setCurrentRow(0)
        self.views.currentItemChanged.connect(self._emit_view)
        self.questions.currentItemChanged.connect(self._emit_question)
        self.search.textChanged.connect(self.search_changed.emit)

    def set_rows(self, rows: list[DesktopQuestionSummary], selected: str | None) -> None:
        """Replace question rows while retaining the current logical ID."""
        self.questions.blockSignals(True)
        self.questions.clear()
        selected_row = -1
        for index, row in enumerate(rows):
            suffix = "  ◉" if row.needs_redraw else ""
            item = QListWidgetItem(f"{row.title}\n{row.id}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, row.id)
            item.setToolTip(f"{row.subject} · {row.question_type} · 难度 {row.difficulty}")
            self.questions.addItem(item)
            if row.id == selected:
                selected_row = index
        self.questions.blockSignals(False)
        if selected_row >= 0:
            self.questions.setCurrentRow(selected_row)
        elif rows:
            self.questions.setCurrentRow(0)

    def current_view(self) -> str:
        """Return the selected saved-view identifier."""
        item = self.views.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole))

    def _emit_view(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is not None:
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

    def __init__(self) -> None:
        super().__init__()
        self.title = QLineEdit()
        self.subject = QLineEdit()
        self.chapter = QLineEdit()
        self.topics = QLineEdit()
        self.question_type = QComboBox()
        self.question_type.addItems([item.value for item in QuestionType])
        self.status = QComboBox()
        self.status.addItems([item.value for item in QuestionStatus])
        self.difficulty = QSpinBox()
        self.difficulty.setRange(1, 5)
        self.language = QLineEdit()
        form = QFormLayout(self)
        form.addRow("标题", self.title)
        form.addRow("学科", self.subject)
        form.addRow("章节", self.chapter)
        form.addRow("主题", self.topics)
        form.addRow("题型", self.question_type)
        form.addRow("状态", self.status)
        form.addRow("难度", self.difficulty)
        form.addRow("语言", self.language)

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

    def __init__(self) -> None:
        super().__init__("题目详情")
        self.setObjectName("detailDrawer")
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        tabs = QTabWidget()
        self.metadata = MetadataPanel()
        self.assets = QListWidget()
        self.source = QPlainTextEdit()
        self.source.setReadOnly(True)
        self.history = QListWidget()
        tabs.addTab(self.metadata, "基础属性")
        tabs.addTab(_padded(self.assets), "图形资产")
        tabs.addTab(_padded(self.source), "来源")
        tabs.addTab(_padded(self.history), "历史")
        self.setWidget(tabs)
        self.setMinimumWidth(280)
        self.assets.itemDoubleClicked.connect(self._activate_asset)

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

    source_edited = Signal(str)
    editor_ready = Signal()
    asset_action = Signal(str, str)
    asset_dropped = Signal(str, str, str)

    def __init__(self) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.editor = QWebEngineView()
        self.preview = QWebEngineView()
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
        self.editor.load(QUrl.fromLocalFile(str(resource)))

    def set_source(self, source: str) -> None:
        """Replace the CodeMirror document using JSON-safe JavaScript."""
        encoded = json.dumps(source, ensure_ascii=False)
        self.editor.page().runJavaScript(f"window.qbankEditor?.setValue({encoded});")

    def set_preview(self, html: str, root: Path) -> None:
        """Load an interactive preview with project-relative local assets."""
        base = QUrl.fromLocalFile(str(root.resolve()) + "/")
        self.preview.setHtml(html, base)

    def set_mode(self, mode: WorkspaceMode) -> None:
        """Show source, preview, or both without destroying either web view."""
        self.editor.setVisible(mode in {"source", "split"})
        self.preview.setVisible(mode in {"preview", "split"})

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


def _padded(widget: QWidget) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(7, 7, 7, 7)
    layout.addWidget(widget)
    return wrapper
