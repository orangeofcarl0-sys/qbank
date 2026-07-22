"""Main Qt Widgets window for focused question editing."""

from __future__ import annotations

import base64
import queue
import threading
import weakref
from functools import partial
from pathlib import Path
from typing import Literal, cast

from PySide6.QtCore import (
    QBuffer,
    QEvent,
    QFileSystemWatcher,
    QIODevice,
    QObject,
    QPoint,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QKeySequence
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
    QToolButton,
)

from qbank.assets import stable_legacy_asset_id
from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.desktop.controller import DesktopController, InteractiveRenderer
from qbank.desktop.preferences_dialog import (
    StudioPreferences,
    StudioPreferencesDialog,
    load_studio_preferences,
    save_studio_preferences,
)
from qbank.desktop.question_dialog import QuestionIdentityDialog
from qbank.desktop.tag_dialogs import TagManagerDialog, TagOverviewDialog
from qbank.desktop.widgets import DetailDrawer, NavigationPane, WebWorkspace, WorkspaceMode
from qbank.errors import QBankError
from qbank.models import (
    AssetManifest,
    DesktopAssetItem,
    DesktopQuestionListResult,
    DiagnosticCode,
    PaperBuildRequest,
    PatchQuestionResult,
    QueryFilters,
)
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
_MUTATING_ASSET_ACTIONS = _ASSET_ACTIONS - {"open-original", "show-directory"}

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


class NavigationSearchBridge(QObject):
    """Deliver background navigation results safely to the Qt UI thread."""

    completed = Signal(int, object, object)

    active = True


SearchJob = tuple[
    int,
    DesktopController,
    str,
    QueryFilters,
]
SearchQueue = queue.Queue[SearchJob | None]


def _search_loop(
    jobs: SearchQueue,
    bridge_ref: weakref.ReferenceType[NavigationSearchBridge],
) -> None:
    while (job := jobs.get()) is not None:
        generation, controller, view, filters = job
        bridge = bridge_ref()
        if bridge is None or not bridge.active:
            continue
        try:
            result = controller.navigation_result(view=view, filters=filters)
            error: object = None
        except Exception as exc:
            result, error = None, exc
        bridge = bridge_ref()
        if bridge is None or not bridge.active:
            continue
        try:
            bridge.completed.emit(generation, result, error)
        except RuntimeError:
            continue


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
        self._search_generation = 0
        self._search_bridge = NavigationSearchBridge(self)
        self._search_jobs: SearchQueue = queue.Queue()
        self._search_thread: threading.Thread | None = None
        self._asset_menu: QMenu | None = None
        self._icon_actions: dict[str, QAction] = {}
        self._paper_actions: dict[str, QAction] = {}
        self._mode_actions: dict[str, QAction] = {}
        self._editing_targets: dict[str, tuple[str, str]] = {}
        self._replacement_window: DesktopMainWindow | None = None
        stored_preferences = load_studio_preferences(theme)
        self.preferences = StudioPreferences(
            theme=theme,
            workspace_mode=stored_preferences.workspace_mode,
            show_detail_drawer=stored_preferences.show_detail_drawer,
            show_project_path=stored_preferences.show_project_path,
        )
        self._workspace_mode: WorkspaceMode = self.preferences.workspace_mode
        self.navigation = NavigationPane(theme)
        self.workspace = WebWorkspace(theme)
        self.drawer = DetailDrawer(
            theme,
            project_root=controller.context.root,
            assets_root=controller.context.paths.assets,
        )
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
        self.drawer.setVisible(self.preferences.show_detail_drawer)
        QTimer.singleShot(0, self._apply_drawer_width)
        self.addToolBar(self._project_toolbar())
        self.addToolBar(self._toolbar())
        self.workspace.set_mode(self._workspace_mode)
        self.statusBar().showMessage("就绪")

    def _apply_drawer_width(self) -> None:
        self.resizeDocks(
            [self.drawer],
            [self.drawer.preferred_width()],
            Qt.Orientation.Horizontal,
        )
        self.drawer.enable_width_persistence()

    def _toolbar(self) -> QToolBar:
        toolbar = QToolBar("编辑")
        toolbar.setObjectName("editorToolbar")
        self._configure_toolbar(toolbar, METRICS.icon_normal)
        self._add_edit_actions(toolbar)
        toolbar.addSeparator()
        self._add_mode_actions(toolbar)
        toolbar.addSeparator()
        self._add_context_actions(toolbar)
        return toolbar

    def _project_toolbar(self) -> QToolBar:
        toolbar = QToolBar("题库")
        toolbar.setObjectName("projectToolbar")
        self._configure_toolbar(toolbar, METRICS.icon_small)
        self.project_name = QLabel()
        self.project_name.setObjectName("projectName")
        self.project_path = QLabel()
        self.project_path.setObjectName("projectPath")
        self.project_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.validation_state = QLabel()
        self.index_state = QLabel()
        for status in (self.validation_state, self.index_state):
            status.setFixedWidth(METRICS.icon_normal + METRICS.space_1)
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.project_name)
        toolbar.addWidget(self.project_path)
        toolbar.addWidget(self.validation_state)
        toolbar.addWidget(self.index_state)
        toolbar.addSeparator()
        for key, label, callback in (
            ("open-project", "打开题库", self._open_project),
            ("add", "新建题目", self._new_question),
            ("copy", "复制题目", self._copy_current_question),
            ("import", "导入题目", self._import_questions),
            ("delete", "删除题目", self._delete_current_question),
        ):
            action = self._action(key, label)
            action.triggered.connect(callback)
            toolbar.addAction(action)
        toolbar.addSeparator()
        self.paper_button = QToolButton()
        self.paper_button.setIcon(icon("paper", self.theme_name))
        self.paper_button.setText("试卷：未选择")
        self.paper_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.paper_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.paper_button.setAccessibleName("当前试卷操作")
        self.paper_button.setMenu(self._paper_menu())
        toolbar.addWidget(self.paper_button)
        return toolbar

    @staticmethod
    def _configure_toolbar(toolbar: QToolBar, icon_size: int) -> None:
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(icon_size, icon_size))
        toolbar.setFixedHeight(METRICS.toolbar_height)

    def _paper_menu(self) -> QMenu:
        menu = QMenu(self)
        for key, label, callback in (
            ("select", "选择试卷…", self._select_paper),
            ("new", "新建试卷…", self._new_paper),
            ("add", "加入题目", self._add_to_paper),
            ("validate", "验证试卷", self._validate_paper),
            ("build", "构建试卷", self._build_paper),
            ("export", "导出试卷…", self._export_paper),
        ):
            action = menu.addAction(label)
            action.triggered.connect(callback)
            self._paper_actions[key] = action
        menu.aboutToShow.connect(self._refresh_paper_actions)
        return menu

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
            action.setChecked(mode == self._workspace_mode)
            action.triggered.connect(
                lambda checked=False, value=mode: self._set_workspace_mode(value)
            )
            group.addAction(action)
            toolbar.addAction(action)
            self._mode_actions[mode] = action

    def _add_context_actions(self, toolbar: QToolBar) -> None:
        language = self.language_mode
        language.addItem("Markdown", "markdown")
        language.addItem("TeX", "tex")
        language.setAccessibleName("编辑器语法")
        language.setToolTip("编辑器语法")
        language.setFixedWidth(124)
        language.currentIndexChanged.connect(partial(self._language_mode_changed, language))
        toolbar.addWidget(language)
        toolbar.addSeparator()
        drawer_action = self.drawer.toggleViewAction()
        drawer_action.setIcon(icon("properties", self.theme_name))
        drawer_action.setText("属性")
        drawer_action.setToolTip("显示或隐藏题目详情")
        self._icon_actions["properties"] = drawer_action
        toolbar.addAction(drawer_action)
        settings = self._action("settings", "Studio 设置")
        settings.triggered.connect(self._show_preferences)
        toolbar.addAction(settings)

    def _action(self, key: str, label: str) -> QAction:
        action = QAction(icon(key, self.theme_name), label, self)
        action.setToolTip(label)
        self._icon_actions[key] = action
        return action

    def _wire_events(self) -> None:
        self.navigation.view_changed.connect(self._refresh_navigation)
        self.navigation.search_changed.connect(self._start_navigation_search)
        self.navigation.filters_changed.connect(self._refresh_navigation)
        self.navigation.question_selected.connect(self._select_question)
        self.navigation.save_view_requested.connect(self._save_current_view)
        self.navigation.rename_view_requested.connect(self._rename_view)
        self.navigation.delete_view_requested.connect(self._delete_view)
        self.navigation.bulk_add_requested.connect(partial(self._bulk_topics, True))
        self.navigation.bulk_remove_requested.connect(partial(self._bulk_topics, False))
        self.navigation.manage_tags_requested.connect(self._show_tag_manager)
        self.navigation.tag_overview_requested.connect(self._show_tag_overview)
        self.workspace.editor_ready.connect(self._editor_ready)
        self.workspace.source_edited.connect(self._source_changed)
        self.workspace.asset_action.connect(self._asset_action)
        self.workspace.asset_dropped.connect(self._asset_dropped)
        self.workspace.context_menu_requested.connect(self._show_asset_context_menu)
        self.workspace.mode_changed.connect(self._workspace_mode_changed)
        self.drawer.asset_activated.connect(self._drawer_asset_activated)
        self.drawer.asset_action_requested.connect(self._asset_action)
        self.drawer.legacy_asset_action_requested.connect(self._legacy_asset_action)
        self.drawer.add_asset_requested.connect(self._add_asset_from_file)
        self.drawer.save_requested.connect(self.save_current)
        self.drawer.restore_requested.connect(self._restore_current)
        self.preview_timer.timeout.connect(self._render_scheduled_preview)
        self.file_watcher.fileChanged.connect(self._editor_file_changed)
        self._search_bridge.completed.connect(self._apply_navigation_search)
        self._wire_metadata_changes()

    def _wire_metadata_changes(self) -> None:
        self.drawer.metadata.metadata_changed.connect(self._metadata_changed)
        self.drawer.metadata.topics.pending_topic_created.connect(self._pending_topic_created)
        self.drawer.source.changed.connect(self._metadata_changed)

    def _language_mode_changed(self, language: ModernComboBox, index: int) -> None:
        self.workspace.set_language_mode(str(language.itemData(index)))

    def _set_workspace_mode(self, mode: str) -> None:
        self._dismiss_asset_menu()
        self._workspace_mode = cast(WorkspaceMode, mode)
        action = self._mode_actions.get(mode)
        if action is not None:
            action.setChecked(True)
        self.workspace.set_mode(self._workspace_mode)

    def _workspace_mode_changed(self, mode: str) -> None:
        del mode
        self._dismiss_asset_menu()

    def _show_preferences(self) -> None:
        current = StudioPreferences(
            theme=self.theme_name,
            workspace_mode=self._workspace_mode,
            show_detail_drawer=self.drawer.isVisible(),
            show_project_path=self.preferences.show_project_path,
        )
        selected = StudioPreferencesDialog.get_preferences(current, self)
        if selected is None:
            return
        save_studio_preferences(selected)
        self.preferences = selected
        if selected.theme != self.theme_name:
            self.set_theme(selected.theme)
        self._set_workspace_mode(selected.workspace_mode)
        self.drawer.setVisible(selected.show_detail_drawer)
        self._update_project_path_label()

    def _drawer_asset_activated(self, asset_id: str) -> None:
        self._asset_action(asset_id, "edit")

    def _load_initial_state(self) -> None:
        self._refresh_navigation_data()
        self._refresh_navigation()
        self._refresh_project_state()

    def _refresh_project_state(self) -> None:
        root = self.controller.context.root
        self.project_name.setText(root.name)
        self._update_project_path_label()
        try:
            status = self.controller.project_status()
        except (QBankError, OSError, ValueError) as exc:
            self.validation_state.setText("×")
            self.validation_state.setObjectName("statusError")
            self.validation_state.setAccessibleName("题库状态不可用")
            self.validation_state.setToolTip(f"题库状态不可用：{exc}")
            self.index_state.clear()
            self.index_state.setAccessibleName("索引状态不可用")
            return
        valid = status.validation_errors == 0
        validation_text = "校验通过" if valid else f"{status.validation_errors} 个校验错误"
        self.validation_state.setText("✓" if valid else "×")
        self.validation_state.setObjectName("statusSuccess" if valid else "statusError")
        self.validation_state.setAccessibleName(validation_text)
        self.validation_state.setToolTip(validation_text)
        index_text = "索引需重建" if status.index_dirty else "索引正常"
        self.index_state.setText("△" if status.index_dirty else "✓")
        self.index_state.setObjectName("statusWarning" if status.index_dirty else "statusSuccess")
        self.index_state.setAccessibleName(index_text)
        self.index_state.setToolTip(index_text)
        for label in (self.validation_state, self.index_state):
            label.style().unpolish(label)
            label.style().polish(label)
        self._refresh_paper_state()

    def _update_project_path_label(self) -> None:
        path = str(self.controller.context.root)
        if self.preferences.show_project_path:
            self.project_path.setText(path)
            self.project_path.setAccessibleName(f"题库路径：{path}")
        else:
            self.project_path.clear()
            self.project_path.setAccessibleName("")
        self.project_path.setToolTip(path)
        self.project_path.updateGeometry()

    def _refresh_paper_state(self) -> None:
        context = self.controller.paper_context
        self.paper_button.setText("试卷" if context.path is None else context.name)
        self.paper_button.setAccessibleName(f"当前试卷操作，{context.name}")
        self.paper_button.setToolTip(
            str(context.path) if context.path is not None else "请选择或新建试卷"
        )
        self._refresh_paper_actions()

    def _refresh_paper_actions(self) -> None:
        context = self.controller.paper_context
        has_paper = context.path is not None
        has_question = self.current_id is not None or bool(self.navigation.selected_question_ids())
        enabled = {
            "select": True,
            "new": has_question,
            "add": has_paper and has_question,
            "validate": has_paper,
            "build": has_paper,
            "export": has_paper,
        }
        for key, action in self._paper_actions.items():
            action.setEnabled(enabled[key])
            action.setStatusTip(
                ""
                if enabled[key]
                else ("请先打开或选择题目" if key == "new" else "请先选择或新建试卷")
            )

    def _open_project(self) -> None:
        if not self._can_leave_current():
            return
        selected = QFileDialog.getExistingDirectory(
            self,
            "打开 qbank 题库（请选择包含 qbank.yaml 的文件夹）",
            str(self.controller.context.root.parent),
        )
        if not selected:
            return
        try:
            context = ProjectContext.from_root(Path(selected))
            services = create_project_services(context)
            controller = DesktopController(
                context,
                services,
                cast(InteractiveRenderer, services.renderer),
            )
            replacement = DesktopMainWindow(controller, self.theme_name)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)
            return
        self._replacement_window = replacement
        replacement.show()
        self.close()

    def _new_question(self) -> None:
        defaults = self.controller.context.config.defaults
        identity = QuestionIdentityDialog.get_new_question(
            self,
            defaults.subject,
            defaults.language,
        )
        if identity is None or identity.title is None:
            return
        try:
            self.controller.create_question(identity.question_id, identity.title, dry_run=True)
            self.controller.create_question(identity.question_id, identity.title, dry_run=False)
            self._refresh_after_question_write(identity.question_id)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _copy_current_question(self) -> None:
        if self.current_id is None:
            return
        try:
            current = self.controller.load_question(self.current_id).question
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)
            return
        defaults = self.controller.context.config.defaults
        identity = QuestionIdentityDialog.get_question_copy(
            self,
            defaults.subject,
            defaults.language,
            (current.id, current.title),
        )
        if identity is None:
            return
        try:
            self.controller.copy_question(self.current_id, identity.question_id, dry_run=True)
            self.controller.copy_question(self.current_id, identity.question_id, dry_run=False)
            self._refresh_after_question_write(identity.question_id)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _import_questions(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "导入题目",
            str(self.controller.context.root),
            "题目交换文件 (*.json *.jsonl)",
        )
        if not selected:
            return
        try:
            planned = self.controller.import_questions(Path(selected), dry_run=True)
            if not planned.ok:
                raise ValueError("导入文件包含无效或冲突题目")
            answer = self._message_box(
                "确认导入",
                f"将导入 {planned.would_write or 0} 道题。",
                QMessageBox.Icon.Question,
                QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Apply:
                return
            self.controller.import_questions(Path(selected), dry_run=False)
            self._refresh_after_question_write(None)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _delete_current_question(self) -> None:
        if self.current_id is None or not self._can_leave_current():
            return
        try:
            planned = self.controller.delete_question(self.current_id, dry_run=True)
            answer = self._message_box(
                "删除题目",
                f"将删除 {planned.id}\n{planned.path}\n\n此操作会写入历史记录。",
                QMessageBox.Icon.Warning,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.controller.delete_question(self.current_id, dry_run=False)
            self.current_id = None
            self._refresh_after_question_write(None)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _refresh_after_question_write(self, question_id: str | None) -> None:
        self._refresh_navigation_data()
        self._refresh_navigation()
        self._refresh_project_state()
        if question_id is not None:
            self._load_question(question_id)

    def _select_paper(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择当前试卷",
            str(self.controller.context.paths.papers),
            "试卷定义 (*.yaml)",
        )
        if not selected:
            return
        try:
            self.controller.load_current_paper(Path(selected))
            self._refresh_paper_state()
            self._refresh_navigation()
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _new_paper(self) -> None:
        ids = self.navigation.selected_question_ids()
        if not ids and self.current_id is not None:
            ids = [self.current_id]
        if not ids:
            self.statusBar().showMessage("请先打开或选择至少一道题", 5000)
            return
        title, accepted = QInputDialog.getText(self, "新建试卷", "试卷标题：")
        if not accepted or not title.strip():
            return
        filename, accepted = QInputDialog.getText(self, "新建试卷", "文件名：", text="paper.yaml")
        if not accepted or not filename.strip():
            return
        path = self.controller.context.paths.papers / filename.strip()
        try:
            self.controller.create_paper(path, title.strip(), ids, dry_run=True)
            self.controller.create_paper(path, title.strip(), ids, dry_run=False)
            self._refresh_paper_state()
            self._refresh_navigation()
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _add_to_paper(self) -> None:
        ids = self.navigation.selected_question_ids()
        if not ids and self.current_id is not None:
            ids = [self.current_id]
        if not ids:
            return
        try:
            self.controller.add_to_current_paper(ids, dry_run=True)
            self.controller.add_to_current_paper(ids, dry_run=False)
            self._refresh_paper_state()
            self._refresh_navigation()
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _validate_paper(self) -> None:
        try:
            result = self.controller.validate_current_paper()
            self._message_box(
                "试卷验证",
                f"{result.summary.questions} 道题，{result.summary.errors} 个错误，"
                f"{result.summary.warnings} 个提示。",
                QMessageBox.Icon.Information if result.ok else QMessageBox.Icon.Warning,
            )
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _build_paper(self) -> None:
        self._run_paper_build(output=None)

    def _export_paper(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "导出试卷",
            str(self.controller.context.paths.exports / "paper.html"),
            "HTML (*.html);;Markdown (*.md);;Word (*.docx)",
        )
        if selected:
            self._run_paper_build(output=Path(selected))

    def _run_paper_build(self, output: Path | None) -> None:
        format_ = output.suffix.lower().lstrip(".") if output is not None else "html"
        if format_ not in {"md", "html", "docx"}:
            format_ = "html"
        try:
            result = self.controller.build_current_paper(
                PaperBuildRequest(
                    output_format=cast(Literal["md", "html", "docx"], format_),
                    output=output,
                )
            )
            self.statusBar().showMessage(f"试卷已生成：{result.output}", 8000)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _refresh_navigation_data(self) -> None:
        data = self.controller.navigation_data()
        self.navigation.set_navigation_data(data)
        self.drawer.metadata.set_taxonomy(data.tags)

    def _refresh_navigation(self, *_: object) -> None:
        self._search_generation += 1
        self.navigation.set_search_loading(False)
        try:
            view = self.navigation.current_view()
            result = self.controller.navigation_result(
                view=view,
                search=self.navigation.search.text(),
                filters=self.navigation.current_filters(),
            )
        except (QBankError, ValueError) as exc:
            self.statusBar().showMessage(f"筛选条件无效：{exc}", 6000)
            return
        self._apply_navigation_result(result)

    def _start_navigation_search(self, _text: str) -> None:
        self._search_generation += 1
        generation = self._search_generation
        if not self.navigation.search.text().strip():
            self.navigation.set_search_loading(False)
            self._refresh_navigation()
            return
        self.navigation.set_search_loading(True)
        if self._search_thread is None:
            self._search_thread = threading.Thread(
                target=_search_loop,
                args=(self._search_jobs, weakref.ref(self._search_bridge)),
                name=f"qbank-search-{id(self):x}",
            )
            self._search_thread.start()
        self._search_jobs.put(
            (
                generation,
                self.controller,
                self.navigation.current_view(),
                self.navigation.current_filters(),
            )
        )

    def _apply_navigation_search(
        self,
        generation: int,
        result: object,
        error: object,
    ) -> None:
        if generation != self._search_generation:
            return
        self.navigation.set_search_loading(False)
        if error is not None:
            self.statusBar().showMessage(f"搜索暂不可用：{error}", 6000)
            return
        if isinstance(result, DesktopQuestionListResult):
            self._apply_navigation_result(result)

    def _apply_navigation_result(self, result: DesktopQuestionListResult) -> None:
        self.navigation.set_rows(result.rows, self.current_id)
        self.navigation.set_tag_rows(result.tags, result.total)

    def _save_current_view(self) -> None:
        name, accepted = QInputDialog.getText(self, "保存筛选视图", "视图名称：")
        if not accepted or not name.strip():
            return
        try:
            filters = self.navigation.current_filters()
            self.controller.save_view(name, filters, dry_run=True)
            self.controller.save_view(name, filters, dry_run=False)
            self._refresh_navigation_data()
            self.navigation.select_view(name.strip())
            self.statusBar().showMessage(f"已保存视图：{name.strip()}", 4000)
        except (QBankError, ValueError) as exc:
            self._show_error(exc)

    def _rename_view(self, old: str) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "重命名筛选视图",
            "新名称：",
            text=old,
        )
        if not accepted or not name.strip() or name.strip() == old:
            return
        try:
            self.controller.rename_view(old, name, dry_run=True)
            self.controller.rename_view(old, name, dry_run=False)
            self._refresh_navigation_data()
            self.navigation.select_view(name.strip())
        except (QBankError, ValueError) as exc:
            self._show_error(exc)

    def _delete_view(self, name: str) -> None:
        answer = QMessageBox.question(
            self,
            "删除筛选视图",
            f"删除保存的视图“{name}”？题目不会被删除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.delete_view(name, dry_run=True)
            self.controller.delete_view(name, dry_run=False)
            self._refresh_navigation_data()
            self.navigation.select_view("all")
        except (QBankError, ValueError) as exc:
            self._show_error(exc)

    def _bulk_topics(self, adding: bool) -> None:
        question_ids = self.navigation.selected_question_ids()
        if not question_ids:
            return
        label = "添加" if adding else "移除"
        value, accepted = QInputDialog.getText(
            self,
            f"批量{label}标签",
            f"为 {len(question_ids)} 道题{label}标签：",
        )
        if not accepted or not value.strip():
            return
        try:
            planned = self.controller.bulk_edit_topics(
                question_ids,
                add=[value] if adding else [],
                remove=[] if adding else [value],
                dry_run=True,
            )
            details = "\n".join(
                f"{change.id}: {', '.join(change.before)} → {', '.join(change.after)}"
                for change in planned.changes[:8]
            )
            if len(planned.changes) > 8:
                details += f"\n…另有 {len(planned.changes) - 8} 道题"
            answer = QMessageBox.question(
                self,
                f"确认批量{label}标签",
                f"将影响 {planned.affected_questions} 道题：\n\n{details}",
                QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Apply:
                return
            self.controller.bulk_edit_topics(
                question_ids,
                add=[value] if adding else [],
                remove=[] if adding else [value],
                dry_run=False,
            )
            self._refresh_navigation_data()
            self._refresh_navigation()
            if self.current_id in question_ids:
                self._load_question(self.current_id)
        except (QBankError, ValueError) as exc:
            self._show_error(exc)

    def _pending_topic_created(self, slug: str) -> None:
        matches = self.controller.possible_tag_synonyms(slug)
        alternatives = [item.slug for item in matches if item.slug != slug]
        if alternatives:
            listed = "、".join(alternatives)
            answer = QMessageBox.question(
                self,
                "确认新建标签",
                f"“{slug}”与现有标签可能同义：{listed}\n\n仍将它作为待整理标签添加吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.drawer.metadata.topics.discard_topic(slug)
                self.statusBar().showMessage(f"已取消新建标签 {slug}", 4000)
                return
            self.statusBar().showMessage(
                f"新标签 {slug} 将标记为待整理；疑似同义：{listed}",
                8000,
            )
        else:
            self.statusBar().showMessage(f"新标签 {slug} 将标记为待整理", 5000)

    def _show_tag_manager(self) -> None:
        dialog = TagManagerDialog(self.controller, self.theme_name, self)
        dialog.changed.connect(self._tag_metadata_changed)
        dialog.exec()

    def _show_tag_overview(self) -> None:
        dialog = TagOverviewDialog(self.controller, self.theme_name, self)
        dialog.filter_requested.connect(self._apply_overview_filter)
        dialog.exec()

    def _tag_metadata_changed(self) -> None:
        self._refresh_navigation_data()
        self._refresh_navigation()
        if self.current_id is not None:
            self._load_question(self.current_id)

    def _apply_overview_filter(self, filters: object) -> None:
        if not isinstance(filters, QueryFilters):
            return
        self.navigation.set_query_state("all", filters)
        self.raise_()
        self.activateWindow()

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
        self.navigation.set_current_question(question_id)
        self.current_source = document.source
        self.drawer.load_document(document)
        self.workspace.set_source(document.source)
        self._saved_source = document.source
        self._saved_metadata = self.drawer.values()
        self.dirty = False
        self._switching = False
        self.drawer.set_dirty_state(0, preview_pending=True)
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
                self.drawer.values(),
                theme=self.theme_name,
            )
        except (QBankError, ValueError) as exc:
            if not preview_result_is_current(
                generation, self._preview_generation, question_id, self.current_id
            ):
                return
            self._preview_loading = False
            self.workspace.show_error(str(exc))
            self._sync_dirty()
            self.statusBar().showMessage(f"预览暂不可用：{exc}", 6000)
            return
        if not preview_result_is_current(
            generation, self._preview_generation, question_id, self.current_id
        ):
            return
        self._preview_loading = False
        self.workspace.set_preview(result.html, self.controller.context.root, question_id)
        self.drawer.set_dirty_state(
            changed_fields_count(
                self.current_source,
                self.drawer.values(),
                self._saved_source,
                self._saved_metadata,
            ),
            preview_pending=False,
        )
        warning = f" · {len(result.warnings)} 个资产提示" if result.warnings else ""
        self.statusBar().showMessage(f"预览已刷新{warning}", 3000)

    def _next_preview_generation(self) -> int:
        self._preview_generation += 1
        return self._preview_generation

    def _sync_dirty(self) -> None:
        self.dirty = snapshot_is_dirty(
            self.current_source,
            self.drawer.values(),
            self._saved_source,
            self._saved_metadata,
        )
        self.drawer.set_dirty_state(
            changed_fields_count(
                self.current_source,
                self.drawer.values(),
                self._saved_source,
                self._saved_metadata,
            ),
            preview_pending=self.preview_timer.isActive() or self._preview_loading,
        )
        self._update_title()

    def validate_current(self) -> None:
        if self.current_id is None:
            return
        try:
            result = self.controller.validate_source(
                self.current_id,
                self.current_source,
                self.drawer.values(),
            )
        except (QBankError, ValueError) as exc:
            self._show_error(exc)
            return
        self.drawer.set_validation(result.ok, len(result.validation_errors))
        self._show_validation(result)

    def save_current(self) -> bool:
        if self.current_id is None:
            return True
        try:
            result = self.controller.save_source(
                self.current_id,
                self.current_source,
                self.drawer.values(),
            )
        except (QBankError, ValueError) as exc:
            self._show_error(exc)
            return False
        if not result.ok:
            self.drawer.set_validation(False, len(result.validation_errors))
            self._show_validation(result)
            return False
        current = self.current_id
        self._load_question(current)
        self._refresh_navigation_data()
        self._refresh_navigation()
        self._refresh_project_state()
        message = "题目已保存、校验并更新索引"
        if any(warning.code == DiagnosticCode.INDEX_DIRTY for warning in result.warnings):
            message = "题目已保存；索引更新失败，已标记为需要重建"
        self.statusBar().showMessage(message, 5000)
        return True

    def _show_validation(self, result: PatchQuestionResult) -> None:
        if result.ok:
            details = (
                f"{len(result.validation_errors)} 个校验错误，"
                f"{len(result.validation_warnings)} 个提示"
            )
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
            document = self.controller.load_question(self.current_id)
            already_managed = any(item.asset_id == asset_id for item in document.assets)
            if (action in _MUTATING_ASSET_ACTIONS or not already_managed) and not (
                self._prepare_asset_mutation()
            ):
                return
            asset_id = self.controller.ensure_logical_asset(self.current_id, asset_id)
            self._dispatch_asset_action(self.current_id, asset_id, action)
            if not already_managed:
                self._reload_after_question_asset_change()
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _legacy_asset_action(self, reference: str, action: str) -> None:
        if self.current_id is None:
            return
        try:
            document = self.controller.load_question(self.current_id)
            item = next(
                (
                    candidate
                    for candidate in document.asset_items
                    if candidate.reference == reference
                ),
                None,
            )
            if item is None:
                raise ValueError(f"资源引用不存在：{reference}")
            if action == "convert":
                self._convert_reference_asset(reference, item.capabilities.convert)
                return
            if action != "open":
                raise ValueError(f"不支持的资源操作：{action}")
            self._open_reference_asset(item)
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _convert_reference_asset(self, reference: str, allowed: bool) -> None:
        if self.current_id is None or not allowed:
            raise ValueError(f"资源引用无效，无法转换：{reference}")
        if not self._prepare_asset_mutation():
            return
        asset_id = stable_legacy_asset_id(reference)
        self.controller.ensure_logical_asset(self.current_id, asset_id)
        self._reload_after_question_asset_change()

    @staticmethod
    def _open_reference_asset(item: DesktopAssetItem) -> None:
        if not item.capabilities.open_reference:
            raise ValueError(f"资源引用不可打开：{item.reference}")
        if item.kind == "external":
            QDesktopServices.openUrl(QUrl(item.reference))
            return
        if item.kind != "local" or item.preview_path is None:
            raise ValueError(f"图片文件不存在或不在 assets 目录内：{item.reference}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(item.preview_path))

    def _add_asset_from_file(self) -> None:
        if self.current_id is None:
            return
        if not self._prepare_asset_mutation():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "添加图形资产",
            str(self.controller.context.root),
            "图像和图形 (*.png *.jpg *.jpeg *.svg *.pdf *.ipe *.tex *.webp *.gif *.bmp);;所有文件 (*)",
        )
        if not path:
            return
        try:
            self.controller.create_asset(self.current_id, path, name=Path(path).name)
            self._reload_after_question_asset_change()
        except (QBankError, OSError, ValueError) as exc:
            self._show_error(exc)

    def _restore_current(self) -> None:
        if self.current_id is not None:
            self._load_question(self.current_id)

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
            action.setEnabled(self._asset_action_available(asset_id, action_name))
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
        # PySide 6.11 accepts the Qt format name as str at runtime despite its stub.
        image.save(buffer, cast(bytes, "PNG"))
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
        if not self._prepare_asset_mutation():
            return
        try:
            already_managed = False
            if asset_id:
                already_managed = any(
                    item.asset_id == asset_id
                    for item in self.controller.load_question(self.current_id).assets
                )
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
            if asset_id and not already_managed:
                self._reload_after_question_asset_change()
            else:
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
        self.drawer.refresh_asset_state(document)
        self._switching = False
        generation = self._next_preview_generation()
        self._preview_loading = True
        self.workspace.show_loading(self.current_id)
        QTimer.singleShot(0, partial(self._render_preview, generation, self.current_id))
        self._refresh_navigation()
        self._sync_dirty()

    def _reload_after_question_asset_change(self) -> None:
        if self.current_id is None:
            return
        current = self.current_id
        self._load_question(current)
        self._refresh_navigation()

    def _prepare_asset_mutation(self) -> bool:
        self._sync_dirty()
        if not self.dirty:
            return True
        choice = self._message_box(
            "先保存题目",
            "当前题目有未保存修改。可先保存、放弃修改或取消资产操作。",
            QMessageBox.Icon.Question,
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            return self.save_current()
        if choice == QMessageBox.StandardButton.Discard and self.current_id is not None:
            self._load_question(self.current_id)
            return True
        return False

    def _asset_action_available(self, asset_id: str, action: str) -> bool:
        if self.current_id is None:
            return False
        document = self.controller.load_question(self.current_id)
        item = next(
            (candidate for candidate in document.asset_items if candidate.asset_id == asset_id),
            None,
        )
        if item is None:
            return False
        capability = {
            "edit": "edit",
            "replace-file": "replace",
            "replace-clipboard": "replace",
            "open-original": "open_original",
            "render": "render",
            "set-render": "set_render",
            "show-directory": "show_directory",
            "restore": "restore",
        }.get(action)
        return bool(capability and getattr(item.capabilities, capability))

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
        project = self.controller.context.root.name
        self.setWindowTitle(f"qbank Studio · {project}{suffix}{marker}")

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
        self.paper_button.setIcon(icon("paper", theme))
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
            self._search_generation += 1
            self.navigation.search_timer.stop()
            self._search_bridge.active = False
            if self._search_thread is not None:
                self._search_jobs.put(None)
                self._search_thread.join()
                self._search_thread = None
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


def changed_fields_count(
    source: str,
    metadata: dict[str, object],
    saved_source: str,
    saved_metadata: dict[str, object],
) -> int:
    """Count edited source plus independently changed Inspector fields."""
    count = int(source != saved_source)
    fields = set(metadata) | set(saved_metadata)
    return count + sum(metadata.get(field) != saved_metadata.get(field) for field in fields)


def preview_result_is_current(
    generation: int,
    current_generation: int,
    question_id: str,
    current_id: str | None,
) -> bool:
    """Reject preview output produced for an obsolete selection or generation."""
    return generation == current_generation and question_id == current_id
