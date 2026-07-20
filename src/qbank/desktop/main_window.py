"""Main Qt Widgets window for focused question editing."""

from __future__ import annotations

import base64
import html
from functools import partial
from pathlib import Path
from typing import cast

from PySide6.QtCore import QBuffer, QEvent, QFileSystemWatcher, QIODevice, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
)

from qbank.desktop.controller import DesktopController, DesktopView
from qbank.desktop.widgets import DetailDrawer, NavigationPane, WebWorkspace, WorkspaceMode
from qbank.errors import QBankError
from qbank.models import AssetManifest, PatchQuestionResult

_ASSET_ACTIONS = frozenset(
    {
        "edit",
        "replace-file",
        "replace-clipboard",
        "open-original",
        "render",
        "set-render",
        "show-directory",
        "restore",
    }
)


class DesktopMainWindow(QMainWindow):
    """Text-first two-and-a-half-column qbank desktop shell."""

    def __init__(self, controller: DesktopController):
        super().__init__()
        self.controller = controller
        self.current_id: str | None = None
        self.current_source = ""
        self.dirty = False
        self._switching = False
        self._editing_targets: dict[str, tuple[str, str]] = {}
        self.navigation = NavigationPane()
        self.workspace = WebWorkspace()
        self.drawer = DetailDrawer()
        self.file_watcher = QFileSystemWatcher(self)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(220)
        self._build_window()
        self._wire_events()
        self._load_initial_state()

    def _build_window(self) -> None:
        self.setWindowTitle("qbank 题目编辑器")
        self.resize(1480, 900)
        shell = self.workspace
        self.setCentralWidget(shell)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, _navigation_dock(self.navigation))
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.drawer)
        self.addToolBar(self._toolbar())
        self.statusBar().showMessage("就绪")
        self.setStyleSheet(
            """
            QMainWindow { background: #f5f6f8; }
            QDockWidget::title { padding: 7px; background: #eef0f3; }
            #navigationPane { background: #f7f8fa; }
            QListWidget { border: 0; background: transparent; }
            QListWidget::item { padding: 7px 5px; border-radius: 4px; }
            QListWidget::item:selected { background: #dfeaff; color: #173b70; }
            QToolBar { spacing: 5px; padding: 4px; border-bottom: 1px solid #dfe2e7; }
            """
        )

    def _toolbar(self) -> QToolBar:
        toolbar = QToolBar("编辑")
        toolbar.setObjectName("editorToolbar")
        save = QAction("保存", self)
        save.setShortcut(QKeySequence.StandardKey.Save)
        save.triggered.connect(self.save_current)
        undo = QAction("撤销", self)
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        undo.triggered.connect(self.workspace.undo)
        redo = QAction("重做", self)
        redo.setShortcut(QKeySequence.StandardKey.Redo)
        redo.triggered.connect(self.workspace.redo)
        validate = QAction("校验", self)
        validate.triggered.connect(self.validate_current)
        toolbar.addActions([save, undo, redo, validate])
        toolbar.addSeparator()
        group = QActionGroup(self)
        group.setExclusive(True)
        for label, mode in (("源码", "source"), ("预览", "preview"), ("分栏", "split")):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(mode == "split")
            action.triggered.connect(
                lambda checked=False, value=mode: self.workspace.set_mode(
                    cast(WorkspaceMode, value)
                )
            )
            group.addAction(action)
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("语法："))
        language = QComboBox()
        language.addItem("Markdown", "markdown")
        language.addItem("TeX", "tex")
        language.currentIndexChanged.connect(partial(self._language_mode_changed, language))
        toolbar.addWidget(language)
        toolbar.addSeparator()
        toolbar.addAction(self.drawer.toggleViewAction())
        return toolbar

    def _wire_events(self) -> None:
        self.navigation.view_changed.connect(self._refresh_navigation)
        self.navigation.search_changed.connect(self._refresh_navigation)
        self.navigation.question_selected.connect(self._select_question)
        self.workspace.editor_ready.connect(self._editor_ready)
        self.workspace.source_edited.connect(self._source_changed)
        self.workspace.asset_action.connect(self._asset_action)
        self.workspace.asset_dropped.connect(self._asset_dropped)
        self.drawer.asset_activated.connect(self._drawer_asset_activated)
        self.preview_timer.timeout.connect(self._render_preview)
        self.file_watcher.fileChanged.connect(self._editor_file_changed)
        self._wire_metadata_changes()

    def _wire_metadata_changes(self) -> None:
        panel = self.drawer.metadata
        for widget in (
            panel.title,
            panel.subject,
            panel.chapter,
            panel.topics,
            panel.language,
        ):
            widget.textEdited.connect(self._metadata_changed)
        panel.question_type.currentTextChanged.connect(self._metadata_changed)
        panel.status.currentTextChanged.connect(self._metadata_changed)
        panel.difficulty.valueChanged.connect(self._metadata_changed)

    def _language_mode_changed(self, language: QComboBox, index: int) -> None:
        self.workspace.set_language_mode(str(language.itemData(index)))

    def _drawer_asset_activated(self, asset_id: str) -> None:
        self._asset_action(asset_id, "edit")

    def _load_initial_state(self) -> None:
        try:
            self.controller.load_current_paper()
        except QBankError as exc:
            self.statusBar().showMessage(str(exc), 8000)
        self._refresh_navigation()

    def _refresh_navigation(self, *_: object) -> None:
        view = cast(DesktopView, self.navigation.current_view())
        rows = self.controller.list_questions(
            view=view,
            search=self.navigation.search.text(),
        )
        self.navigation.set_rows(rows, self.current_id)

    def _select_question(self, question_id: str) -> None:
        if self._switching or question_id == self.current_id:
            return
        if not self._can_leave_current():
            self._refresh_navigation()
            return
        self._load_question(question_id)

    def _load_question(self, question_id: str) -> None:
        try:
            document = self.controller.load_question(question_id)
        except QBankError as exc:
            self._show_error(exc)
            return
        self._switching = True
        self.current_id = question_id
        self.current_source = document.source
        self.dirty = False
        self.drawer.load_document(document)
        self.workspace.set_source(document.source)
        self._switching = False
        self._render_preview()
        self._update_title()

    def _editor_ready(self) -> None:
        if self.current_source:
            self.workspace.set_source(self.current_source)

    def _source_changed(self, source: str) -> None:
        if self._switching or source == self.current_source:
            return
        self.current_source = source
        self.dirty = True
        self.preview_timer.start()
        self._update_title()

    def _metadata_changed(self, *_: object) -> None:
        if self._switching or self.current_id is None:
            return
        self.dirty = True
        self.preview_timer.start()
        self._update_title()

    def _render_preview(self) -> None:
        if self.current_id is None:
            return
        try:
            result = self.controller.preview_source(
                self.current_id,
                self.current_source,
                self.drawer.metadata.values(),
            )
        except (QBankError, ValueError) as exc:
            self.workspace.set_preview(_error_page(str(exc)), self.controller.context.root)
            self.statusBar().showMessage(f"预览暂不可用：{exc}", 6000)
            return
        self.workspace.set_preview(result.html, self.controller.context.root)
        warning = f" · {len(result.warnings)} 个资产提示" if result.warnings else ""
        self.statusBar().showMessage(f"预览已刷新{warning}", 3000)

    def validate_current(self) -> None:
        if self.current_id is None:
            return
        try:
            result = self.controller.validate_source(
                self.current_id,
                self.current_source,
                self.drawer.metadata.values(),
            )
        except (QBankError, ValueError) as exc:
            self._show_error(exc)
            return
        self._show_validation(result)

    def save_current(self) -> bool:
        if self.current_id is None:
            return True
        try:
            result = self.controller.save_source(
                self.current_id,
                self.current_source,
                self.drawer.metadata.values(),
            )
        except (QBankError, ValueError) as exc:
            self._show_error(exc)
            return False
        if not result.ok:
            self._show_validation(result)
            return False
        current = self.current_id
        self._load_question(current)
        self._refresh_navigation()
        self.statusBar().showMessage("题目已保存、校验并更新索引", 5000)
        return True

    def _show_validation(self, result: PatchQuestionResult) -> None:
        if result.ok:
            details = f"{len(result.changes)} 个字段将变化"
            if result.validation_warnings:
                details += f"，{len(result.validation_warnings)} 个提示"
            QMessageBox.information(self, "校验通过", details)
            return
        messages = "\n".join(item.message for item in result.validation_errors)
        QMessageBox.warning(self, "校验未通过", messages or "题目内容无效")

    def _asset_action(self, asset_id: str, action: str) -> None:
        if self.current_id is None or action not in _ASSET_ACTIONS:
            return
        try:
            asset_id = self.controller.ensure_logical_asset(self.current_id, asset_id)
            self._dispatch_asset_action(self.current_id, asset_id, action)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _dispatch_asset_action(self, question_id: str, asset_id: str, action: str) -> None:
        if action == "edit":
            self._begin_edit(question_id, asset_id)
        elif action == "replace-file":
            self._replace_file(question_id, asset_id)
        elif action == "replace-clipboard":
            self._replace_clipboard(question_id, asset_id)
        elif action == "open-original":
            self.controller.open_original(question_id, asset_id)
        elif action == "render":
            self.controller.render_asset(question_id, asset_id)
            self._refresh_after_asset_change()
        elif action == "set-render":
            self._choose_render(question_id, asset_id)
        elif action == "show-directory":
            self.controller.show_asset_directory(question_id, asset_id)
        elif action == "restore":
            self.controller.restore_asset(question_id, asset_id)
            self._refresh_after_asset_change()

    def _begin_edit(self, question_id: str, asset_id: str) -> None:
        target = self.controller.begin_asset_edit(question_id, asset_id)
        normalized = str(Path(target).resolve())
        self._editing_targets[normalized] = (question_id, asset_id)
        if normalized not in self.file_watcher.files():
            self.file_watcher.addPath(normalized)
        self._refresh_after_asset_change()
        self.statusBar().showMessage("已在首选编辑器中打开受管工作副本", 5000)

    def _replace_file(self, question_id: str, asset_id: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择替换文件",
            str(self.controller.context.root),
            "图形 (*.png *.jpg *.jpeg *.svg *.pdf *.ipe *.tex *.webp *.gif *.bmp);;所有文件 (*)",
        )
        if not path:
            return
        self.controller.replace_asset(question_id, asset_id, path)
        self._refresh_after_asset_change()

    def _replace_clipboard(self, question_id: str, asset_id: str) -> None:
        image = QApplication.clipboard().image()
        if image.isNull():
            raise ValueError("剪贴板中没有图片")
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, b"PNG")
        encoded = base64.b64encode(buffer.data().data()).decode("ascii")
        self.controller.replace_asset(
            question_id,
            asset_id,
            f"data:image/png;base64,{encoded}",
            name="clipboard.png",
        )
        self._refresh_after_asset_change()

    def _choose_render(self, question_id: str, asset_id: str) -> None:
        manifest = self._manifest(asset_id)
        choices = [
            item.representation_id
            for item in manifest.representations
            if item.renderable and not item.stale
        ]
        if not choices:
            raise ValueError("该资产没有可用的渲染表示")
        selected, accepted = QInputDialog.getItem(
            self,
            "设为首选表示",
            "representation",
            choices,
            editable=False,
        )
        if accepted:
            self.controller.set_preferred_render(
                question_id,
                asset_id,
                str(selected),
            )
            self._refresh_after_asset_change()

    def _asset_dropped(self, asset_id: str, name: str, data_uri: str) -> None:
        if self.current_id is None:
            return
        try:
            if asset_id:
                asset_id = self.controller.ensure_logical_asset(self.current_id, asset_id)
                self.controller.replace_asset(
                    self.current_id,
                    asset_id,
                    data_uri,
                    name=name,
                )
            else:
                result = self.controller.create_asset(
                    self.current_id,
                    data_uri,
                    name=name,
                )
                self.workspace.insert_asset(result.asset_id)
            self._refresh_after_asset_change()
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _editor_file_changed(self, path: str) -> None:
        normalized = str(Path(path).resolve())
        if Path(normalized).is_file() and normalized not in self.file_watcher.files():
            self.file_watcher.addPath(normalized)
        QTimer.singleShot(350, lambda: self._reconcile_target(normalized))

    def _reconcile_target(self, path: str) -> None:
        target = self._editing_targets.get(path)
        if target is None:
            return
        try:
            self.controller.reconcile_asset(*target)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)
            return
        self._refresh_after_asset_change()
        self.statusBar().showMessage(
            "检测到编辑源变化；旧渲染已标记 stale，可一键重新渲染",
            7000,
        )

    def _refresh_after_asset_change(self) -> None:
        if self.current_id is None:
            return
        document = self.controller.load_question(self.current_id)
        self._switching = True
        self.drawer.load_document(document)
        self._switching = False
        self._render_preview()
        self._refresh_navigation()

    def _manifest(self, asset_id: str) -> AssetManifest:
        if self.current_id is None:
            raise ValueError("尚未选择题目")
        document = self.controller.load_question(self.current_id)
        for manifest in document.assets:
            if manifest.asset_id == asset_id:
                return manifest
        raise ValueError(f"资产不存在：{asset_id}")

    def _can_leave_current(self) -> bool:
        if not self.dirty:
            return True
        choice = QMessageBox.question(
            self,
            "尚未保存",
            "当前题目有未保存修改。是否先保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            return self.save_current()
        return choice == QMessageBox.StandardButton.Discard

    def _update_title(self) -> None:
        marker = " *" if self.dirty else ""
        suffix = f" — {self.current_id}" if self.current_id else ""
        self.setWindowTitle(f"qbank 题目编辑器{suffix}{marker}")

    def _show_error(self, error: object) -> None:
        QMessageBox.critical(self, "操作失败", str(error))
        self.statusBar().showMessage(str(error), 8000)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            for path in tuple(self._editing_targets):
                QTimer.singleShot(0, partial(self._reconcile_target, path))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._can_leave_current():
            event.accept()
        else:
            event.ignore()


def _navigation_dock(navigation: NavigationPane) -> QDockWidget:
    dock = QDockWidget("题目")
    dock.setObjectName("questionNavigation")
    dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
    dock.setWidget(navigation)
    return dock


def _error_page(message: str) -> str:
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<style>body{font:14px system-ui;padding:30px;color:#9b2c2c}</style>"
        f"<h2>预览错误</h2><pre>{html.escape(message)}</pre>"
    )
