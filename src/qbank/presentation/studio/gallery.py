"""Long-lived component gallery for Studio design states."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from qbank.desktop.widgets import MetadataPanel, WebWorkspace
from qbank.presentation.studio.design.controls import ModernComboBox
from qbank.presentation.studio.design.icons import icon
from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.web_theme import css_variables


class StudioGallery(QMainWindow):
    """Interactive inventory of production Studio components and states."""

    theme_name: ThemeName

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self.setObjectName("studioGallery")
        self.setWindowTitle(f"qbank Studio 组件画廊 · {theme}")
        self.resize(1380, 900)
        self.addToolBar(self._toolbar())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(20, 20, 20, 28)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.addWidget(self._controls(), 0, 0)
        grid.addWidget(self._navigation(), 0, 1, 2, 1)
        grid.addWidget(self._inspector(), 1, 0)
        grid.addWidget(self._documents(), 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        self.statusBar().showMessage("组件状态 · 浅色与深色使用相同语义 token")

    def _toolbar(self) -> QToolBar:
        toolbar = QToolBar("编辑操作")
        for key, label in (
            ("save", "保存"),
            ("undo", "撤销"),
            ("redo", "重做"),
            ("validate", "校验"),
        ):
            action = toolbar.addAction(icon(key, self.theme_name), label)
            action.setToolTip(f"{label}题目")
        toolbar.addSeparator()
        disabled = toolbar.addAction(icon("render", self.theme_name), "渲染中")
        disabled.setEnabled(False)
        return toolbar

    def _controls(self) -> QFrame:
        panel, layout = _section("控件与状态")
        row = QHBoxLayout()
        primary = QPushButton("保存题目")
        primary.setIcon(icon("save", self.theme_name))
        row.addWidget(primary)
        row.addWidget(QPushButton("次要操作"))
        disabled = QPushButton("不可用")
        disabled.setEnabled(False)
        row.addWidget(disabled)
        row.addStretch()
        layout.addLayout(row)
        search = QLineEdit()
        search.setPlaceholderText("搜索题目、主题或公式")
        search.setClearButtonEnabled(True)
        layout.addWidget(search)
        states = QHBoxLayout()
        for object_name, text in (
            ("statusSuccess", "✓ 校验通过"),
            ("statusWarning", "△ 2 个资源提示"),
            ("statusError", "× 结构错误"),
        ):
            label = QLabel(text)
            label.setObjectName(object_name)
            states.addWidget(label)
        states.addStretch()
        layout.addLayout(states)
        fields = QHBoxLayout()
        combo = ModernComboBox(self.theme_name)
        combo.addItems(["draft", "reviewed", "final"])
        fields.addWidget(combo)
        fields.addWidget(QCheckBox("加入当前试卷"))
        menu_button = QPushButton("图像操作菜单")
        menu_button.setIcon(icon("edit", self.theme_name))
        menu_button.clicked.connect(partial(self._show_asset_menu, menu_button))
        fields.addWidget(menu_button)
        dialog_button = QPushButton("确认对话框")
        dialog_button.clicked.connect(self._show_dialog)
        fields.addWidget(dialog_button)
        fields.addStretch()
        layout.addLayout(fields)
        return panel

    def _inspector(self) -> QFrame:
        panel, layout = _section("题目详情属性检查器")
        inspector = MetadataPanel(self.theme_name)
        inspector.title.setText("理想运算放大器基本性质")
        inspector.subject.setText("electronics")
        inspector.chapter.setText("amplifiers")
        inspector.topics.setText("op-amp, ideal-model")
        inspector.question_type.setCurrentText("multiple_choice")
        inspector.status.setCurrentText("reviewed")
        inspector.difficulty.setValue(1)
        inspector.language.setText("zh-CN")
        layout.addWidget(inspector)
        return panel

    def _navigation(self) -> QFrame:
        panel, layout = _section("导航与题目列表")
        filter_label = QLabel("当前筛选：全部题目")
        filter_label.setObjectName("activeFilter")
        layout.addWidget(filter_label)
        views = QListWidget()
        views.addItems(["全部题目  24", "草稿  6", "图形待重绘  3", "当前试卷  8"])
        views.setCurrentRow(0)
        views.setMaximumHeight(126)
        layout.addWidget(views)
        questions = QListWidget()
        questions.addItems(
            [
                "Michelson 干涉仪光程差变化\nOPT-INT-0001 · reviewed",
                "单缝衍射中央主极大\nOPT-DIF-0001 · draft",
                "干涉条纹示意图观察\nOPT-IMG-0001 · final",
            ]
        )
        questions.setCurrentRow(0)
        layout.addWidget(questions)
        return panel

    def _documents(self) -> QFrame:
        panel, layout = _section("编辑、预览与反馈")
        tabs = QTabWidget()
        self.web_workspace = WebWorkspace(self.theme_name)
        self.web_workspace.setMinimumHeight(360)
        source = (
            "## 题目\n\nMichelson 干涉仪的一面反射镜移动 $d$。"
            "求光程差变化。\n\n## 答案\n\n$\\Delta L = 2d\\cos\\theta$"
        )
        self.web_workspace.editor_ready.connect(lambda: self.web_workspace.set_source(source))
        self.web_workspace.set_preview(
            _gallery_preview_html(self.theme_name),
            Path.cwd(),
            "OPT-INT-0001",
        )
        tabs.addTab(self.web_workspace, "CodeMirror / Markdown / MathJax")
        tabs.addTab(self._state_samples(), "加载 / 空 / 错误")
        layout.addWidget(tabs)
        return panel

    def _state_samples(self) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        for name, detail, state in (
            ("加载中", "正在生成 OPT-INT-0001 预览…", "activeFilter"),
            ("空状态", "当前筛选没有题目", "sectionLabel"),
            ("校验错误", "choice_answer: 选项与答案不一致", "statusError"),
        ):
            box = QFrame()
            box.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QVBoxLayout(box)
            heading = QLabel(name)
            heading.setObjectName(state)
            layout.addWidget(heading)
            text = QLabel(detail)
            text.setWordWrap(True)
            layout.addWidget(text)
            row.addWidget(box)
        return widget

    def _show_asset_menu(self, anchor: QPushButton) -> None:
        menu = QMenu(self)
        for key, label in (
            ("edit", "用 Ipe 编辑"),
            ("replace-file", "替换为本地文件"),
            ("replace-clipboard", "从剪贴板替换"),
            ("open-original", "打开原始参考图"),
            ("render", "重新渲染"),
            ("set-render", "设为首选表示"),
            ("show-directory", "在资源管理器中显示"),
            ("restore", "恢复上一版本"),
        ):
            menu.addAction(icon(key, self.theme_name), label)
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _show_dialog(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("尚未保存")
        dialog.setText("当前题目有未保存修改。是否先保存？")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.Save)
        dialog.setAccessibleName("未保存修改确认")
        dialog.exec()


def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
    panel = QFrame()
    panel.setFrameShape(QFrame.Shape.StyledPanel)
    layout = QVBoxLayout(panel)
    heading = QLabel(title)
    heading.setObjectName("sectionLabel")
    layout.addWidget(heading)
    return panel, layout


def _gallery_preview_html(theme: ThemeName) -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'>
    <script>window.MathJax={{tex:{{inlineMath:[[\"$\",\"$\"],[\"\\\\(\",\"\\\\)\"]]}}}};</script>
    <script defer src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js'></script>
    <style>{css_variables(theme)}body{{margin:0;padding:24px 28px;background:var(--qbank-surface-elevated);color:var(--qbank-text-primary);font:15px/1.6 var(--qbank-document-font)}}
    h1{{font-size:21px}}.meta{{color:var(--qbank-text-secondary)}}.asset{{margin-top:28px;padding:22px;border:2px solid var(--qbank-border-subtle);border-radius:var(--qbank-radius-medium);text-align:center}}.asset:hover{{border-color:var(--qbank-focus)}}</style>
    </head><body data-question-id='OPT-INT-0001'><h1>Michelson 干涉仪光程差变化</h1><div class='meta'>OPT-INT-0001 · optics · reviewed</div>
    <p>若反射镜沿光轴移动 <em>d</em>，求两束光重新叠加时的光程差变化。</p>
    <p>答案：$\\Delta L = 2d\\cos\\theta$</p>
    <div class='asset'>图像对象 · interferometer-layout · 右键可操作</div></body></html>"""
