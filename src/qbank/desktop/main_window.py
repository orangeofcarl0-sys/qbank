"""Main Qt Widgets window for focused question editing."""

from __future__ import annotations

import base64
from functools import partial
from pathlib import Path
from typing import cast

from PySide6.QtCore import (
    QBuffer,
    QEvent,
    QFileSystemWatcher,
    QIODevice,
    QPoint,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QToolBar,
)

from qbank.desktop.controller import DesktopController, DesktopView
from qbank.desktop.widgets import DetailDrawer, NavigationPane, WebWorkspace, WorkspaceMode
from qbank.errors import QBankError
from qbank.models import AssetManifest, PatchQuestionResult
from qbank.presentation.studio.design.controls import ModernComboBox
from qbank.presentation.studio.design.icons import icon
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.stylesheet import apply_theme

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

_ASSET_MENU_ITEMS = (
    ("edit", "用 Ipe 编辑"),
    ("replace-file", "替换为本地文件"),
    ("replace-clipboard", "从剪贴板替换"),
    ("open-original", "打开原始参考图"),
    ("render", "重新渲染"),
    ("set-render", "设为首选表示"),
    ("show-directory", "在资源管理器中显示"),
    ("restore", "恢复上一版本"),
)


class DesktopMainWindow(QMainWindow):
    """Text-first two-and-a-half-column qbank desktop shell."""

    theme_name: ThemeName

    def __init__(self, controller: DesktopController, theme: ThemeName = "light"):
        super().__init__()
        self.controller = controller
        self.theme_name = theme
        self.current_id: str | None = None
        self.current_source = ""
        self._saved_source = ""
        self._saved_metadata: dict[str, object] = {}
        self.dirty = False
        self._switching = False
        self._preview_generation = 0
        self._scheduled_preview_generation = 0
        self._preview_loading = False
        self._asset_menu: QMenu | None = None
        self._icon_actions: dict[str, QAction] = {}
        self._editing_targets: dict[str, tuple[str, str]] = {}
        self.navigation = NavigationPane(theme)
        self.workspace = WebWorkspace(theme)
        self.drawer = DetailDrawer(theme)
        self.language_mode = ModernComboBox(theme)
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

    def _toolbar(self) -> QToolBar:
        toolbar = QToolBar("编辑")
        toolbar.setObjectName("editorToolbar")
        toolbar.setIconSize(QSize(METRICS.icon_normal, METRICS.icon_normal))
        self._add_edit_actions(toolbar)
        toolbar.addSeparator()
        self._add_mode_actions(toolbar)
        toolbar.addSeparator()
        self._add_context_actions(toolbar)
        return toolbar

    def _add_edit_actions(self, toolbar: QToolBar) -> None:
        save = self._action("save", "保存")
        save.setShortcut(QKeySequence.StandardKey.Save)
        save.triggered.connect(self.save_current)
        undo = self._action("undo", "撤销")
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        undo.triggered.connect(self._undo_current_focus)
        redo = self._action("redo", "重做")
        redo.setShortcut(QKeySequence.StandardKey.Redo)
        redo.triggered.connect(self._redo_current_focus)
        validate = self._action("validate", "校验")
        validate.triggered.connect(self.validate_current)
        toolbar.addActions([save, undo, redo, validate])

    def _undo_current_focus(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit) or (
            isinstance(focus, QPlainTextEdit) and not focus.isReadOnly()
        ):
            focus.undo()
        else:
            self.workspace.undo()

    def _redo_current_focus(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit) or (
            isinstance(focus, QPlainTextEdit) and not focus.isReadOnly()
        ):
            focus.redo()
        else:
            self.workspace.redo()

    def _add_mode_actions(self, toolbar: QToolBar) -> None:
        group = QActionGroup(self)
        group.setExclusive(True)
        for label, mode in (("源码", "source"), ("预览", "preview"), ("分栏", "split")):
            action = self._action(mode, label)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(mode == "split")
            action.triggered.connect(
                lambda checked=False, value=mode: self._set_workspace_mode(value)
            )
            group.addAction(action)
            toolbar.addAction(action)

    def _add_context_actions(self, toolbar: QToolBar) -> None:
        toolbar.addWidget(QLabel("语法："))
        language = self.language_mode
        language.addItem("Markdown", "markdown")
        language.addItem("TeX", "tex")
        language.currentIndexChanged.connect(partial(self._language_mode_changed, language))
        toolbar.addWidget(language)
        toolbar.addSeparator()
        drawer_action = self.drawer.toggleViewAction()
        drawer_action.setIcon(icon("properties", self.theme_name))
        drawer_action.setText("属性")
        drawer_action.setToolTip("显示或隐藏题目详情")
        self._icon_actions["properties"] = drawer_action
        toolbar.addAction(drawer_action)
        toolbar.addSeparator()
        theme = self._action("theme", "切换主题")
        theme.setCheckable(True)
        theme.setChecked(self.theme_name == "dark")
        theme.triggered.connect(self._toggle_theme)
        toolbar.addAction(theme)

    def _action(self, key: str, label: str) -> QAction:
        action = QAction(icon(key, self.theme_name), label, self)
        action.setToolTip(label)
        self._icon_actions[key] = action
        return action

    def _wire_events(self) -> None:
        self.navigation.view_changed.connect(self._refresh_navigation)
        self.navigation.search_changed.connect(self._refresh_navigation)
        self.navigation.question_selected.connect(self._select_question)
        self.workspace.editor_ready.connect(self._editor_ready)
        self.workspace.source_edited.connect(self._source_changed)
        self.workspace.asset_action.connect(self._asset_action)
        self.workspace.asset_dropped.connect(self._asset_dropped)
        self.workspace.context_menu_requested.connect(self._show_asset_context_menu)
        self.workspace.mode_changed.connect(self._workspace_mode_changed)
        self.drawer.asset_activated.connect(self._drawer_asset_activated)
        self.preview_timer.timeout.connect(self._render_scheduled_preview)
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

    def _language_mode_changed(self, language: ModernComboBox, index: int) -> None:
        self.workspace.set_language_mode(str(language.itemData(index)))

    def _set_workspace_mode(self, mode: str) -> None:
        self._dismiss_asset_menu()
        self.workspace.set_mode(cast(WorkspaceMode, mode))

    def _workspace_mode_changed(self, mode: str) -> None:
        del mode
        self._dismiss_asset_menu()

    def _drawer_asset_activated(self, asset_id: str) -> None:
        self._asset_action(asset_id, "edit")

    def _load_initial_state(self) -> None:
        try:
            self.controller.load_current_paper()
        except (QBankError, OSError, ValueError) as exc:
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
        self.preview_timer.stop()
        generation = self._next_preview_generation()
        self._dismiss_asset_menu()
        self._preview_loading = True
        self.workspace.show_loading(question_id)
        try:
            document = self.controller.load_question(question_id)
        except (QBankError, OSError, ValueError) as exc:
            self._preview_loading = False
            self.workspace.show_error(str(exc))
            self._show_error(exc)
            self._refresh_navigation()
            return
        self._switching = True
        self.current_id = question_id
        self.current_source = document.source
        self.drawer.load_document(document)
        self.workspace.set_source(document.source)
        self._saved_source = document.source
        self._saved_metadata = self.drawer.metadata.values()
        self.dirty = False
        self._switching = False
        self._update_title()
        QTimer.singleShot(0, partial(self._render_preview, generation, question_id))

    def _editor_ready(self) -> None:
        if self.current_source:
            self.workspace.set_source(self.current_source)

    def _source_changed(self, source: str) -> None:
        if self._switching or source == self.current_source:
            return
        self.current_source = source
        self._schedule_preview()
        self._sync_dirty()

    def _metadata_changed(self, *_: object) -> None:
        if self._switching or self.current_id is None:
            return
        self._schedule_preview()
        self._sync_dirty()

    def _schedule_preview(self) -> None:
        self._scheduled_preview_generation = self._next_preview_generation()
        self.workspace.set_asset_actions_enabled(False)
        self.preview_timer.start()

    def _render_scheduled_preview(self) -> None:
        if self.current_id is not None:
            self._render_preview(self._scheduled_preview_generation, self.current_id)

    def _render_preview(self, generation: int, question_id: str) -> None:
        if not preview_result_is_current(
            generation, self._preview_generation, question_id, self.current_id
        ):
            return
        try:
            result = self.controller.preview_source(
                question_id,
                self.current_source,
                self.drawer.metadata.values(),
                theme=self.theme_name,
            )
        except (QBankError, ValueError) as exc:
            if not preview_result_is_current(
                generation, self._preview_generation, question_id, self.current_id
            ):
                return
            self._preview_loading = False
            self.workspace.show_error(str(exc))
            self.statusBar().showMessage(f"预览暂不可用：{exc}", 6000)
            return
        if not preview_result_is_current(
            generation, self._preview_generation, question_id, self.current_id
        ):
            return
        self._preview_loading = False
        self.workspace.set_preview(result.html, self.controller.context.root, question_id)
        warning = f" · {len(result.warnings)} 个资产提示" if result.warnings else ""
        self.statusBar().showMessage(f"预览已刷新{warning}", 3000)

    def _next_preview_generation(self) -> int:
        self._preview_generation += 1
        return self._preview_generation

    def _sync_dirty(self) -> None:
        self.dirty = snapshot_is_dirty(
            self.current_source,
            self.drawer.metadata.values(),
            self._saved_source,
            self._saved_metadata,
        )
        self._update_title()

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
            self._message_box("校验通过", details, QMessageBox.Icon.Information)
            return
        messages = "\n".join(item.message for item in result.validation_errors)
        self._message_box(
            "校验未通过",
            messages or "题目内容无效",
            QMessageBox.Icon.Warning,
        )

    def _asset_action(self, asset_id: str, action: str) -> None:
        if self.current_id is None or action not in _ASSET_ACTIONS or self._preview_loading:
            return
        try:
            asset_id = self.controller.ensure_logical_asset(self.current_id, asset_id)
            self._dispatch_asset_action(self.current_id, asset_id, action)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _show_asset_context_menu(self, asset_id: str, x: int, y: int) -> None:
        if self._preview_loading or not self.workspace.asset_actions_enabled:
            return
        self._dismiss_asset_menu()
        menu = QMenu(self)
        menu.setObjectName("assetContextMenu")
        menu.setAccessibleName(f"图像 {asset_id} 操作")
        for action_name, label in _ASSET_MENU_ITEMS:
            action = menu.addAction(icon(action_name, self.theme_name), label)
            action.setData((asset_id, action_name))
            action.triggered.connect(
                lambda checked=False, aid=asset_id, name=action_name: self._asset_action(aid, name)
            )
        menu.aboutToHide.connect(self._clear_asset_menu)
        self._asset_menu = menu
        menu.popup(self.workspace.preview.mapToGlobal(QPoint(x, y)))

    def _clear_asset_menu(self) -> None:
        menu, self._asset_menu = self._asset_menu, None
        if menu is not None:
            menu.deleteLater()

    def _dismiss_asset_menu(self) -> None:
        if self._asset_menu is not None:
            self._asset_menu.close()

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
        generation = self._next_preview_generation()
        self._preview_loading = True
        self.workspace.show_loading(self.current_id)
        QTimer.singleShot(0, partial(self._render_preview, generation, self.current_id))
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
        choice = self._message_box(
            "尚未保存",
            "当前题目有未保存修改。是否先保存？",
            QMessageBox.Icon.Question,
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
        self._message_box("操作失败", str(error), QMessageBox.Icon.Critical)
        self.statusBar().showMessage(str(error), 8000)

    def _message_box(
        self,
        title: str,
        text: str,
        message_icon: QMessageBox.Icon,
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        default: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
    ) -> QMessageBox.StandardButton:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setIcon(message_icon)
        dialog.setStandardButtons(buttons)
        dialog.setDefaultButton(default)
        dialog.setAccessibleName(title)
        dialog.setAccessibleDescription(text)
        for button in dialog.buttons():
            button.setAccessibleName(button.text().replace("&", ""))
        return QMessageBox.StandardButton(dialog.exec())

    def _toggle_theme(self, checked: bool) -> None:
        self.set_theme("dark" if checked else "light")

    def set_theme(self, theme: ThemeName) -> None:
        """Apply one semantic theme to Qt, CodeMirror, and preview surfaces."""
        self.theme_name = theme
        application = cast(QApplication, QApplication.instance())
        apply_theme(application, theme)
        self.navigation.set_theme(theme)
        self.workspace.set_theme(theme)
        self.drawer.set_theme(theme)
        self.language_mode.set_theme(theme)
        for key, action in self._icon_actions.items():
            action.setIcon(icon(key, theme))
        if self.current_id is not None:
            generation = self._next_preview_generation()
            self._preview_loading = True
            self.workspace.show_loading(self.current_id)
            QTimer.singleShot(0, partial(self._render_preview, generation, self.current_id))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() != QEvent.Type.ActivationChange:
            return
        self._dismiss_asset_menu()
        if self.isActiveWindow():
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


def snapshot_is_dirty(
    source: str,
    metadata: dict[str, object],
    saved_source: str,
    saved_metadata: dict[str, object],
) -> bool:
    """Compare the live editor state with its last authoritative snapshot."""
    return source != saved_source or metadata != saved_metadata


def preview_result_is_current(
    generation: int,
    current_generation: int,
    question_id: str,
    current_id: str | None,
) -> bool:
    """Reject preview output produced for an obsolete selection or generation."""
    return generation == current_generation and question_id == current_id
