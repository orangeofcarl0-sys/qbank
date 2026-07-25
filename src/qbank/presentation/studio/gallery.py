"""Long-lived component gallery for Studio design states."""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qbank.legacy_qt.preferences_dialog import StudioPreferences, StudioPreferencesForm
from qbank.legacy_qt.question_dialog import QuestionIdentityForm
from qbank.legacy_qt.widgets import (
    InspectorSummary,
    MetadataPanel,
    NavigationPane,
    WebWorkspace,
)
from qbank.models import (
    DesktopNavigationData,
    DesktopQuestionDocument,
    DesktopQuestionSummary,
    QueryFilters,
    Question,
    QuestionStatus,
    QuestionType,
    SavedView,
    TagStatus,
    TagUsage,
    TaxonomyTag,
)
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
        search.setPlaceholderText("搜索题目、标签或公式")
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
        layout.addWidget(self._project_context_prototype())
        layout.addWidget(self._selection_prototype())
        layout.addWidget(self._question_identity_prototype())
        layout.addWidget(self._preferences_prototype())
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

    @staticmethod
    def _project_context_prototype() -> QFrame:
        project = QFrame()
        project.setObjectName("projectContextBar")
        row = QHBoxLayout(project)
        row.setContentsMargins(8, 4, 4, 4)
        row.addWidget(QLabel("demo-bank"))
        path = QLabel("workspace/demo-bank")
        path.setObjectName("fieldHint")
        row.addWidget(path, 1)
        healthy = QLabel("✓ 校验通过")
        healthy.setObjectName("statusSuccess")
        row.addWidget(healthy)
        index = QLabel("✓ 索引正常")
        index.setObjectName("statusSuccess")
        row.addWidget(index)
        paper = QLabel("试卷：未选择")
        paper.setObjectName("fieldHint")
        row.addWidget(paper)
        return project

    def _selection_prototype(self) -> QFrame:
        selection = QFrame()
        selection.setObjectName("selectionBar")
        row = QHBoxLayout(selection)
        row.setContentsMargins(8, 4, 4, 4)
        selected = QLabel("已选择 2 道题 · OPT-INT-0001、OPT-DIF-0001")
        selected.setObjectName("selectionSummary")
        selected.setMinimumWidth(0)
        selected.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(selected, 1)
        for icon_name, accessible in (
            ("add", "为已选择题目添加标签"),
            ("remove", "从已选择题目移除标签"),
        ):
            button = QToolButton()
            button.setObjectName("selectionAction")
            button.setText("标签")
            button.setIcon(icon(icon_name, self.theme_name, semantic="accent"))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setFixedWidth(68)
            button.setAccessibleName(accessible)
            row.addWidget(button)
        return selection

    @staticmethod
    def _question_identity_prototype() -> QFrame:
        panel = QFrame()
        panel.setObjectName("inspectorSection")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("新建题目 · 完整身份信息")
        title.setObjectName("inspectorSectionLabel")
        layout.addWidget(title)
        form = QuestionIdentityForm("new", "general", "zh-CN")
        form.id_input.setText("OPT-NEW-0001")
        form.title_input.setText("新建题目预览")
        layout.addWidget(form)
        return panel

    def _preferences_prototype(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("inspectorSection")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("Studio 设置 · 次级界面偏好")
        title.setObjectName("inspectorSectionLabel")
        layout.addWidget(title)
        layout.addWidget(StudioPreferencesForm(StudioPreferences(), self.theme_name))
        return panel

    def _inspector(self) -> QFrame:
        panel, layout = _section("题目详情属性检查器")
        document = _gallery_document()
        summary = InspectorSummary(self.theme_name)
        summary.load_document(document)
        summary.set_warning(["2 项修改尚未保存", "图形待重绘"])
        layout.addWidget(summary)
        inspector = MetadataPanel(self.theme_name)
        inspector.load_document(document)
        layout.addWidget(inspector)
        return panel

    def _navigation(self) -> QFrame:
        panel, layout = _section("导航与题目列表")
        navigation = NavigationPane(self.theme_name)
        navigation.set_navigation_data(
            DesktopNavigationData(
                views=[
                    SavedView(name="all", protected=True),
                    SavedView(name="draft", protected=True),
                    SavedView(name="图形覆盖待审", filters=QueryFilters(topics=["diffraction"])),
                ],
                tags=[
                    TagUsage(
                        slug="interference",
                        count=12,
                        registered=True,
                        metadata=TaxonomyTag(
                            slug="interference",
                            name_zh="干涉",
                            aliases=["相干叠加"],
                            color="#527da6",
                        ),
                    ),
                    TagUsage(
                        slug="diffraction",
                        count=7,
                        registered=True,
                        metadata=TaxonomyTag(
                            slug="diffraction",
                            name_zh="衍射",
                            color="#7a6aa6",
                        ),
                    ),
                    TagUsage(
                        slug="needs-review",
                        count=3,
                        registered=True,
                        metadata=TaxonomyTag(
                            slug="needs-review",
                            name_zh="待整理",
                            status=TagStatus.PENDING,
                        ),
                    ),
                ],
                statuses=["draft", "reviewed"],
                question_types=["calculation", "short_answer"],
                chapters=["interferometry", "diffraction"],
                years=[2025, 2026],
            )
        )
        navigation.set_rows(
            [
                DesktopQuestionSummary(
                    id="OPT-INT-0001",
                    title="Michelson 干涉仪光程差变化",
                    subject="optics",
                    status="reviewed",
                    question_type="calculation",
                    difficulty=2,
                    needs_redraw=False,
                ),
                DesktopQuestionSummary(
                    id="OPT-DIF-0001",
                    title="单缝衍射中央主极大",
                    subject="optics",
                    status="draft",
                    question_type="short_answer",
                    difficulty=3,
                    needs_redraw=True,
                ),
            ],
            "OPT-INT-0001",
        )
        navigation.select_view("图形覆盖待审")
        navigation.set_transient_filters(
            QueryFilters(
                text="干涉",
                topics=["interference"],
                excluded_topics=["needs-review"],
                topic_mode="and",
                status=QuestionStatus.REVIEWED,
                question_type=QuestionType.CALCULATION,
                chapter="interferometry",
                year=2026,
                difficulty_min=2,
                difficulty_max=4,
            )
        )
        layout.addWidget(navigation)
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


def _gallery_document() -> DesktopQuestionDocument:
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
            "source": {"type": "manual", "reference": "实验讲义 2025 第 3 题"},
            "assets": [],
            "stem_md": "理想运算放大器有哪些基本性质？",
        }
    )
    return DesktopQuestionDocument(question=question, source="## 题目", assets=[], history=[])
