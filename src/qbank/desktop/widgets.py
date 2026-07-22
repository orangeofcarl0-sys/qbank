"""Reusable Qt Widgets for the lightweight two-and-a-half-column shell."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Literal, cast

from PySide6.QtCore import (
    QItemSelectionModel,
    QSettings,
    QSize,
    QStringListModel,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QColor,
    QFocusEvent,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QPixmap,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QDockWidget,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qbank.desktop.bridges import EditorBridge, PreviewBridge
from qbank.desktop.state import SelectionState
from qbank.models import (
    AssetCapabilities,
    AssetManifest,
    DesktopAssetItem,
    DesktopNavigationData,
    DesktopQuestionDocument,
    DesktopQuestionSummary,
    QueryFilters,
    QuestionStatus,
    QuestionType,
    SavedView,
    TagUsage,
    normalize_tag_slug,
)
from qbank.presentation.studio.design.controls import FlowLayout, ModernComboBox, ModernSpinBox
from qbank.presentation.studio.design.icons import icon
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import ThemeName, palette_for
from qbank.presentation.studio.design.web_theme import css_variables, state_page

WorkspaceMode = Literal["source", "preview", "split"]

_QUESTION_TYPE_LABELS = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "true_false": "判断题",
    "fill_blank": "填空题",
    "calculation": "计算题",
    "short_answer": "简答题",
    "proof": "证明题",
    "essay": "论述题",
    "composite": "综合题",
    "other": "其他",
}
_QUESTION_STATUS_LABELS = {
    "draft": "草稿",
    "reviewed": "已审阅",
    "verified": "已核验",
    "deprecated": "已停用",
}
_SUBJECT_LABELS = {
    "electronics": "电子学",
    "mathematics": "数学",
    "optics": "光学",
    "signals": "信号与系统",
}
_LANGUAGE_LABELS = {
    "zh-CN": "简体中文",
    "zh-TW": "繁体中文",
    "en": "英语",
    "en-US": "英语（美国）",
}
_ASSET_STATUS_LABELS = {
    "raw": "原始",
    "needs_redraw": "待重绘",
    "editing": "编辑中",
    "reviewed": "已审阅",
    "final": "已定稿",
    "failed": "处理失败",
}
_DIFFICULTY_LABELS = {1: "基础", 2: "较易", 3: "中等", 4: "较难", 5: "挑战"}
_TOPIC_SUGGESTIONS = (
    "calculus",
    "diffraction",
    "fft",
    "interference",
    "op-amp",
    "signal-processing",
)


class FilterChipBar(QWidget):
    """Compact removable chips describing the active navigation query."""

    remove_requested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("filterChipBar")
        self._layout = FlowLayout(self)

    def set_chips(self, chips: list[tuple[str, str, str]]) -> None:
        """Replace chips as key, value, and user-facing label tuples."""
        _clear_layout(self._layout)
        for key, value, label in chips:
            button = QToolButton()
            button.setObjectName("filterChip")
            visible = button.fontMetrics().elidedText(
                label,
                Qt.TextElideMode.ElideRight,
                METRICS.nav_width // 2 - METRICS.space_6,
            )
            button.setText(f"{visible}  ×")
            button.setToolTip(f"移除筛选：{label}")
            button.setAccessibleName(f"移除筛选 {label}")
            button.setMaximumWidth(METRICS.nav_width // 2 - METRICS.space_1)
            button.clicked.connect(
                lambda checked=False, item_key=key, item_value=value: self.remove_requested.emit(
                    item_key, item_value
                )
            )
            self._layout.addWidget(button)
        self.setVisible(bool(chips))


class FacetFilterPanel(QFrame):
    """Small OpenRefine-style field facets kept secondary to the question list."""

    changed = Signal()

    def __init__(self, theme: ThemeName) -> None:
        super().__init__()
        self.setObjectName("facetFilterPanel")
        self.status = ModernComboBox(theme)
        self.question_type = ModernComboBox(theme)
        self.subject = QLineEdit()
        self.chapter = ModernComboBox(theme)
        self.language = QLineEdit()
        self.year = ModernComboBox(theme)
        self.difficulty_min = ModernComboBox(theme)
        self.difficulty_max = ModernComboBox(theme)
        layout = QGridLayout(self)
        layout.setContentsMargins(
            METRICS.space_2, METRICS.space_2, METRICS.space_2, METRICS.space_2
        )
        layout.setHorizontalSpacing(METRICS.space_1)
        layout.setVerticalSpacing(METRICS.space_1)
        controls = (
            ("状态", self.status),
            ("题型", self.question_type),
            ("学科", self.subject),
            ("章节", self.chapter),
            ("语言", self.language),
            ("年份", self.year),
            ("难度从", self.difficulty_min),
            ("难度至", self.difficulty_max),
        )
        for index, (label, control) in enumerate(controls):
            row, column = divmod(index, 2)
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(_field_label(label))
            box.addWidget(control)
            layout.addLayout(box, row, column)
            if isinstance(control, ModernComboBox):
                control.currentIndexChanged.connect(self._emit_changed)
            else:
                _line_edit(control).editingFinished.connect(self.changed.emit)
        self.setVisible(False)

    def set_data(self, data: DesktopNavigationData) -> None:
        """Populate deterministic facet choices while retaining selections."""
        _set_combo_choices(self.status, [item.value for item in QuestionStatus])
        _set_combo_choices(self.question_type, [item.value for item in QuestionType])
        _set_combo_choices(self.chapter, data.chapters)
        _set_combo_choices(self.year, [str(year) for year in data.years])
        _set_combo_choices(self.difficulty_min, [str(value) for value in range(1, 6)])
        _set_combo_choices(self.difficulty_max, [str(value) for value in range(1, 6)])

    def filters(self, text: str, topics: TagSelector) -> QueryFilters:
        """Build one validated query from all transient UI facets."""
        status = _combo_optional(self.status)
        question_type = _combo_optional(self.question_type)
        return QueryFilters(
            text=text or None,
            topics=topics.included(),
            excluded_topics=topics.excluded(),
            topic_mode=topics.topic_mode(),
            status=QuestionStatus(status) if status else None,
            question_type=QuestionType(question_type) if question_type else None,
            subject=self.subject.text().strip() or None,
            chapter=_combo_optional(self.chapter),
            language=self.language.text().strip() or None,
            year=_combo_optional_int(self.year),
            difficulty_min=_combo_optional_int(self.difficulty_min),
            difficulty_max=_combo_optional_int(self.difficulty_max),
            limit=100_000,
        )

    def set_filters(self, filters: QueryFilters) -> None:
        """Restore a saved view into the facet controls."""
        for control, value in (
            (self.status, filters.status.value if filters.status else None),
            (self.question_type, filters.question_type.value if filters.question_type else None),
            (self.chapter, filters.chapter),
            (self.year, str(filters.year) if filters.year else None),
            (
                self.difficulty_min,
                str(filters.difficulty_min) if filters.difficulty_min else None,
            ),
            (
                self.difficulty_max,
                str(filters.difficulty_max) if filters.difficulty_max else None,
            ),
        ):
            _select_or_add_combo_data(control, value)
        self.subject.setText(filters.subject or "")
        self.language.setText(filters.language or "")

    def clear(self) -> None:
        """Reset all field facets."""
        for control in (
            self.status,
            self.question_type,
            self.chapter,
            self.year,
            self.difficulty_min,
            self.difficulty_max,
        ):
            control.setCurrentIndex(0)
        self.subject.clear()
        self.language.clear()

    def set_theme(self, theme: ThemeName) -> None:
        for control in (
            self.status,
            self.question_type,
            self.chapter,
            self.year,
            self.difficulty_min,
            self.difficulty_max,
        ):
            control.set_theme(theme)

    def _emit_changed(self, _index: int) -> None:
        self.changed.emit()


class TagFacetList(QListWidget):
    """Keyboard-operable list whose rows cycle through tag filter states."""

    cycle_requested = Signal(str)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            item = cast(QListWidgetItem | None, self.currentItem())
            if item is not None:
                self.cycle_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))
                event.accept()
                return
        super().keyPressEvent(event)


class TagSelector(QFrame):
    """Collapsible three-state tag facet scoped to the current result set."""

    changed = Signal()
    manage_requested = Signal()
    overview_requested = Signal()

    def __init__(self, theme: ThemeName) -> None:
        super().__init__()
        self.theme_name = theme
        self.setObjectName("tagSelector")
        self._rows: list[TagUsage] = []
        self._catalog: dict[str, TagUsage] = {}
        self._included: set[str] = set()
        self._excluded: set[str] = set()
        self._current_slug: str | None = None
        self._create_controls(theme)
        self._build_layout()
        self._connect_signals()

    def _create_controls(self, theme: ThemeName) -> None:
        self.toggle = QToolButton()
        self.toggle.setObjectName("tagSelectorToggle")
        self.toggle.setText("标签")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolTip("展开标签筛选；每行可明确选择包含、排除或清除")
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.manage = QToolButton()
        self.manage.setText("管理")
        self.manage.setToolTip("打开标签管理器")
        self.overview = QToolButton()
        self.overview.setText("概览")
        self.overview.setToolTip("打开标签频次、共现与覆盖图")
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索标签")
        self.search.setAccessibleName("搜索标签")
        self.sort = ModernComboBox(theme)
        self.sort.setAccessibleName("标签排序方式")
        self.sort.setToolTip("标签排序方式")
        self.sort.addItem("按数量", "count")
        self.sort.addItem("按名称", "name")
        self.mode = ModernComboBox(theme)
        self.mode.setAccessibleName("多标签匹配方式")
        self.mode.setToolTip("多个包含标签使用 AND 或 OR 匹配")
        self.mode.addItem("AND", "and")
        self.mode.addItem("OR", "or")
        self.list = TagFacetList()
        self.list.setObjectName("tagFacetList")
        self.list.setAccessibleName("标签包含与排除筛选")
        self.list.setMaximumHeight(METRICS.control_height * 6)
        self.body = QWidget()

    def _build_layout(self) -> None:
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(METRICS.space_1)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.sort)
        search_row.addWidget(self.mode)
        body_layout.addLayout(search_row)
        body_layout.addWidget(self.list)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, METRICS.space_1, 0, 0)
        layout.setSpacing(METRICS.space_1)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.toggle, 1)
        header.addWidget(self.manage)
        header.addWidget(self.overview)
        layout.addLayout(header)
        layout.addWidget(self.body)

    def _connect_signals(self) -> None:
        self.toggle.toggled.connect(self._toggle_body)
        self.search.textChanged.connect(self._refresh)
        self.sort.currentIndexChanged.connect(self._refresh)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.list.itemClicked.connect(self._cycle_item)
        self.list.cycle_requested.connect(self._cycle_slug)
        self.manage.clicked.connect(self.manage_requested.emit)
        self.overview.clicked.connect(self.overview_requested.emit)

    def set_rows(self, rows: list[TagUsage]) -> None:
        """Replace counts using only tags present in the current result set."""
        self._catalog.update({row.slug: row for row in rows})
        by_slug = {row.slug: row for row in rows}
        for slug in self._included | self._excluded:
            if slug not in by_slug:
                previous = self._catalog.get(slug)
                by_slug[slug] = TagUsage(
                    slug=slug,
                    count=0,
                    registered=previous.registered if previous is not None else False,
                    metadata=previous.metadata if previous is not None else None,
                )
        self._rows = list(by_slug.values())
        self._refresh()

    def set_filters(
        self, included: list[str], excluded: list[str], topic_mode: str = "and"
    ) -> None:
        """Restore include, exclude, and AND/OR state from a saved query."""
        self._included = set(included)
        self._excluded = set(excluded)
        _select_combo_data(self.mode, topic_mode)
        self._refresh()

    def included(self) -> list[str]:
        return sorted(self._included)

    def excluded(self) -> list[str]:
        return sorted(self._excluded)

    def topic_mode(self) -> Literal["and", "or"]:
        return cast(Literal["and", "or"], str(self.mode.currentData()))

    def clear(self) -> None:
        self._included.clear()
        self._excluded.clear()
        self.search.clear()
        self.mode.setCurrentIndex(0)
        self._refresh()

    def remove(self, slug: str) -> None:
        self._included.discard(slug)
        self._excluded.discard(slug)
        self._refresh()

    def set_theme(self, theme: ThemeName) -> None:
        self.theme_name = theme
        self.sort.set_theme(theme)
        self.mode.set_theme(theme)
        self._refresh()

    def _toggle_body(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _mode_changed(self, _index: int) -> None:
        self.changed.emit()

    def _refresh(self, *_: object) -> None:
        query = self.search.text().strip().casefold()
        rows = [
            row
            for row in self._rows
            if not query
            or query in row.slug.casefold()
            or (
                row.metadata is not None
                and any(query in term for term in row.metadata.search_terms())
            )
        ]
        if self.sort.currentData() == "count":
            rows.sort(key=lambda row: (-row.count, row.slug))
        else:
            rows.sort(key=lambda row: row.slug)
        self.list.clear()
        for row in rows:
            self._add_row(row)
        if self._current_slug is not None:
            for index in range(self.list.count()):
                item = self.list.item(index)
                if str(item.data(Qt.ItemDataRole.UserRole)) == self._current_slug:
                    self.list.setCurrentItem(item)
                    break
        active = len(self._included) + len(self._excluded)
        suffix = f" · {active} 项筛选" if active else ""
        self.toggle.setText(f"标签 · {len(rows)}{suffix}")

    def _add_row(self, row: TagUsage) -> None:
        included = row.slug in self._included
        excluded = row.slug in self._excluded
        state_label = "包含" if included else "排除" if excluded else "未选择"
        label = row.metadata.name_zh if row.metadata and row.metadata.name_zh else row.slug
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, row.slug)
        item.setData(
            Qt.ItemDataRole.AccessibleTextRole,
            f"{state_label}标签 {label}，{row.count} 道题",
        )
        item.setData(
            Qt.ItemDataRole.AccessibleDescriptionRole,
            "单击或按空格循环：包含、排除、未选择；也可使用行内按钮",
        )
        item.setToolTip(
            f"{self._tooltip(row)}\n当前：{state_label}\n单击或按空格循环：包含 → 排除 → 未选择"
        )
        self.list.addItem(item)
        row_widget = self._row_widget(row, label, included, excluded)
        item.setSizeHint(row_widget.sizeHint())
        self.list.setItemWidget(item, row_widget)

    def _row_widget(
        self,
        row: TagUsage,
        label: str,
        included: bool,
        excluded: bool,
    ) -> QFrame:
        widget = QFrame()
        widget.setObjectName("tagFacetRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(METRICS.space_1, 0, METRICS.space_1, 0)
        layout.setSpacing(METRICS.space_1)
        if row.metadata is not None and row.metadata.color is not None:
            color = QLabel("●")
            color.setStyleSheet(f"color: {row.metadata.color};")
            layout.addWidget(color)
        name = QLabel(label)
        name.setToolTip(self._tooltip(row))
        layout.addWidget(name, 1)
        count = QLabel(str(row.count))
        count.setObjectName("tagCount")
        layout.addWidget(count)
        states = (
            ("+", "include", included, f"包含标签 {label}"),
            ("−", "exclude", excluded, f"排除标签 {label}"),
            ("×", "clear", not included and not excluded, f"清除标签筛选 {label}"),
        )
        for state in states:
            layout.addWidget(self._state_button(row.slug, *state))
        return widget

    def _state_button(
        self,
        slug: str,
        text: str,
        state: str,
        active: bool,
        accessible: str,
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName("tagStateChip")
        button.setText(text)
        button.setCheckable(state != "clear")
        button.setChecked(active and state != "clear")
        button.setEnabled(state != "clear" or not active)
        button.setAccessibleName(accessible)
        button.setToolTip(accessible)
        button.clicked.connect(
            lambda checked=False, value=slug, name=state: self._set_state(value, name)
        )
        return button

    def _cycle_item(self, item: QListWidgetItem) -> None:
        self.list.setCurrentItem(item)
        self.list.setFocus(Qt.FocusReason.MouseFocusReason)
        self._cycle_slug(str(item.data(Qt.ItemDataRole.UserRole)))

    def _cycle_slug(self, slug: str) -> None:
        self._current_slug = slug
        self.list.setFocus(Qt.FocusReason.ShortcutFocusReason)
        if slug in self._included:
            state = "exclude"
        elif slug in self._excluded:
            state = "clear"
        else:
            state = "include"
        self._set_state(slug, state)

    def _set_state(self, slug: str, state: str) -> None:
        self._current_slug = slug
        self._included.discard(slug)
        self._excluded.discard(slug)
        if state == "include":
            self._included.add(slug)
        elif state == "exclude":
            self._excluded.add(slug)
        self._refresh()
        self.changed.emit()

    @staticmethod
    def _tooltip(row: TagUsage) -> str:
        if row.metadata is None:
            return f"{row.slug} · {row.count} 道题 · 未注册，待整理"
        aliases = "、".join(row.metadata.aliases)
        detail = f" · 别名：{aliases}" if aliases else ""
        return f"{row.slug} · {row.count} 道题 · {row.metadata.status.value}{detail}"


class NavigationPane(QWidget):
    """Zotero-style saved views and question navigation."""

    theme_name: ThemeName

    view_changed = Signal(str)
    question_selected = Signal(str)
    search_changed = Signal(str)
    filters_changed = Signal()
    save_view_requested = Signal()
    rename_view_requested = Signal(str)
    delete_view_requested = Signal(str)
    bulk_add_requested = Signal()
    bulk_remove_requested = Signal()
    manage_tags_requested = Signal()
    tag_overview_requested = Signal()

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self._syncing = False
        self._result_total: int | None = None
        self._current_question_visible: bool | None = None
        self._search_loading = False
        self._query_filters = QueryFilters(limit=100_000)
        self._selection_state = SelectionState()
        self._view_definitions: dict[str, SavedView] = {}
        self.setObjectName("navigationPane")
        self.setMinimumWidth(METRICS.nav_width)
        self.setMaximumWidth(METRICS.nav_width + METRICS.space_8)
        self._create_controls(theme)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self._build_layout()
        self.set_navigation_data(self._initial_navigation_data())
        self.views.setCurrentRow(0)
        self._update_active_filter()
        self._connect_signals()
        self._update_selection_bar()

    def _create_controls(self, theme: ThemeName) -> None:
        self._create_query_controls(theme)
        self._create_view_controls(theme)
        self._create_result_controls(theme)

    def _create_query_controls(self, theme: ThemeName) -> None:
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索题目、标签或公式")
        self.search.setAccessibleName("搜索题目")
        self.clear_filter = QToolButton()
        self.clear_filter.setIcon(icon("clear", theme))
        self.clear_filter.setIconSize(QSize(METRICS.icon_small, METRICS.icon_small))
        self.clear_filter.setToolTip("清除搜索和筛选")
        self.clear_filter.setAccessibleName("清除搜索和筛选")
        self.active_filter = QLabel()
        self.active_filter.setObjectName("activeFilter")
        self.active_filter.setWordWrap(True)
        self.filter_chips = FilterChipBar()
        self.all_questions = QToolButton()
        self.all_questions.setText("全部题目")
        self.all_questions.setCheckable(True)
        self.all_questions.setChecked(True)
        self.all_questions.setAccessibleName("显示全部题目")
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("高级筛选")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_body = QWidget()
        self.advanced_scroll = QScrollArea()
        self.advanced_scroll.setObjectName("advancedFilterScroll")
        self.advanced_scroll.setAccessibleName("高级筛选内容")
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.advanced_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.advanced_scroll.setMaximumHeight(METRICS.control_height * 10)
        self.advanced_scroll.setVisible(False)
        self.filters_toggle = QToolButton()
        self.filters_toggle.setText("字段分面")
        self.filters_toggle.setCheckable(True)
        self.filters_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.filters_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.facets = FacetFilterPanel(theme)

    def _create_result_controls(self, theme: ThemeName) -> None:
        self.questions = QListWidget()
        self.questions.setAccessibleName("题目列表")
        self.questions.setAlternatingRowColors(True)
        self.questions.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.questions.setMinimumHeight(METRICS.control_height * 5)
        self.bulk_add = QToolButton()
        self.bulk_add.setObjectName("selectionAction")
        self.bulk_add.setText("标签")
        self.bulk_add.setIcon(icon("add", theme, semantic="accent"))
        self.bulk_add.setIconSize(QSize(METRICS.icon_small, METRICS.icon_small))
        self.bulk_add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.bulk_add.setFixedWidth(68)
        self.bulk_add.setAccessibleName("为选中的题目批量添加标签")
        self.bulk_add.setToolTip("为选中的题目批量添加标签")
        self.bulk_remove = QToolButton()
        self.bulk_remove.setObjectName("selectionAction")
        self.bulk_remove.setText("标签")
        self.bulk_remove.setIcon(icon("remove", theme, semantic="accent"))
        self.bulk_remove.setIconSize(QSize(METRICS.icon_small, METRICS.icon_small))
        self.bulk_remove.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.bulk_remove.setFixedWidth(68)
        self.bulk_remove.setAccessibleName("从选中的题目批量移除标签")
        self.bulk_remove.setToolTip("从选中的题目批量移除标签")
        self.selection_bar = QFrame()
        self.selection_bar.setObjectName("selectionBar")
        self.selection_summary = QLabel("未选择题目")
        self.selection_summary.setObjectName("selectionSummary")
        self.selection_summary.setMinimumWidth(0)
        self.selection_summary.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.tags = TagSelector(theme)
        self.empty_hint = _empty_hint()

    def _create_view_controls(self, theme: ThemeName) -> None:
        self.views = QListWidget()
        self.views.setAccessibleName("保存的筛选视图")
        self.views.setMaximumHeight(METRICS.control_height * 6)
        self.save_view = QToolButton()
        self.save_view.setText("保存视图")
        self.save_view.setIcon(icon("save", theme))
        self.save_view.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.save_view.setToolTip("将当前组合筛选保存为视图")
        self.save_view.setAccessibleName("保存当前筛选视图")
        self.view_actions = QToolButton()
        self.view_actions.setText("⋯")
        self.view_actions.setToolTip("恢复、重命名或删除当前视图")
        self.view_actions.setAccessibleName("当前视图操作")

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 8, 10)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.clear_filter)
        layout.addLayout(search_row)
        layout.addWidget(self.active_filter)
        layout.addWidget(self.filter_chips)
        layout.addWidget(self.all_questions)
        question_header = QHBoxLayout()
        question_header.setContentsMargins(0, 0, 0, 0)
        question_header.addWidget(QLabel("题目"))
        question_header.addStretch()
        layout.addLayout(question_header)
        layout.addWidget(self.empty_hint)
        layout.addWidget(self.questions, 1)
        selection_layout = QHBoxLayout(self.selection_bar)
        selection_layout.setContentsMargins(
            METRICS.space_2,
            METRICS.space_1,
            METRICS.space_1,
            METRICS.space_1,
        )
        selection_layout.setSpacing(METRICS.space_1)
        selection_layout.addWidget(self.selection_summary, 1)
        selection_layout.addWidget(self.bulk_add)
        selection_layout.addWidget(self.bulk_remove)
        layout.addWidget(self.selection_bar)
        layout.addWidget(self.advanced_toggle)
        advanced = QVBoxLayout(self.advanced_body)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setSpacing(METRICS.space_1)
        advanced.addWidget(self.views)
        view_actions = QHBoxLayout()
        view_actions.setContentsMargins(0, 0, 0, 0)
        view_actions.addWidget(self.save_view)
        view_actions.addWidget(self.view_actions)
        advanced.addLayout(view_actions)
        advanced.addWidget(self.filters_toggle)
        advanced.addWidget(self.facets)
        advanced.addWidget(self.tags)
        self.advanced_scroll.setWidget(self.advanced_body)
        layout.addWidget(self.advanced_scroll)

    @staticmethod
    def _initial_navigation_data() -> DesktopNavigationData:
        return DesktopNavigationData(
            views=[
                SavedView(name="all", protected=True),
                SavedView(
                    name="draft",
                    filters=QueryFilters(status=QuestionStatus.DRAFT),
                    protected=True,
                ),
                SavedView(name="needs_redraw", protected=True),
                SavedView(name="current_paper", protected=True),
            ],
            tags=[],
            statuses=[],
            question_types=[],
            subjects=[],
            chapters=[],
            languages=[],
            years=[],
        )

    def set_navigation_data(self, data: DesktopNavigationData) -> None:
        """Load saved views and available field facets without losing selection."""
        current = self.current_view() if self.views.count() else "all"
        self._view_definitions = {view.name: view for view in data.views}
        self.views.blockSignals(True)
        self.views.clear()
        selected_row = 0
        labels = {
            "all": "全部题目",
            "draft": "草稿",
            "needs_redraw": "图形待重绘",
            "current_paper": "当前试卷",
        }
        for index, view in enumerate(data.views):
            item = QListWidgetItem(labels.get(view.name, view.name))
            item.setData(Qt.ItemDataRole.UserRole, view.name)
            item.setData(Qt.ItemDataRole.UserRole + 1, view.protected)
            self.views.addItem(item)
            if view.name == current:
                selected_row = index
        self.views.setCurrentRow(selected_row)
        self.views.blockSignals(False)
        self.facets.set_data(data)
        self._set_filter_controls(self._query_filters)
        self.tags.set_rows(data.tags)
        self._update_active_filter()

    def set_tag_rows(self, rows: list[TagUsage], total: int) -> None:
        """Update current-result tag counts and result summary together."""
        self.tags.set_rows(rows)
        self._result_total = total
        self._update_active_filter()

    def _connect_signals(self) -> None:
        self.views.currentItemChanged.connect(self._emit_view)
        self.all_questions.clicked.connect(self.clear_filters)
        self.questions.currentItemChanged.connect(self._emit_question)
        self.questions.itemSelectionChanged.connect(self._selection_changed)
        self.search.textChanged.connect(self._search_updated)
        self.search_timer.timeout.connect(self._emit_debounced_search)
        self.clear_filter.clicked.connect(self.clear_filters)
        self.filter_chips.remove_requested.connect(self._remove_chip)
        self.facets.changed.connect(self._filters_changed)
        self.tags.changed.connect(self._filters_changed)
        self.filters_toggle.toggled.connect(self._toggle_facets)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.save_view.clicked.connect(self.save_view_requested.emit)
        self.view_actions.clicked.connect(self._show_view_actions)
        self.bulk_add.clicked.connect(self.bulk_add_requested.emit)
        self.bulk_remove.clicked.connect(self.bulk_remove_requested.emit)
        self.tags.manage_requested.connect(self.manage_tags_requested.emit)
        self.tags.overview_requested.connect(self.tag_overview_requested.emit)

    def set_rows(self, rows: list[DesktopQuestionSummary], selected: str | None) -> None:
        """Replace question rows while retaining the current logical ID."""
        retained_selection = set(self._selection_state.selected_ids)
        result_ids = tuple(row.id for row in rows)
        self._selection_state = self._selection_state.with_results(result_ids, selected)
        retained_selection &= set(result_ids)
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
            item.setSelected(row.id in retained_selection)
            if row.id == selected:
                selected_row = index
        if selected_row >= 0:
            self.questions.setCurrentItem(
                self.questions.item(selected_row),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        elif selected is None and rows:
            self.questions.setCurrentItem(
                self.questions.item(0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        else:
            self.questions.setCurrentRow(-1)
        self.questions.blockSignals(False)
        self._selection_state = self._selection_state.with_selection(
            tuple(row.id for row in rows if row.id in retained_selection)
        )
        self._update_selection_bar()
        self.empty_hint.setVisible(not rows)
        self._current_question_visible = selected is None or selected_row >= 0
        self._update_active_filter()
        if selected is None and rows:
            self.question_selected.emit(rows[0].id)

    def set_current_question(self, question_id: str | None) -> None:
        """Update current-result membership without rebuilding or selecting rows."""
        self._current_question_visible = question_id is None or any(
            str(self.questions.item(index).data(Qt.ItemDataRole.UserRole)) == question_id
            for index in range(self.questions.count())
        )
        self._update_active_filter()

    def current_view(self) -> str:
        """Return the selected saved-view identifier."""
        item = cast(QListWidgetItem | None, self.views.currentItem())
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else "all"

    def current_filters(self) -> QueryFilters:
        """Return the authoritative query model projected into the controls."""
        return self._query_filters

    def selected_question_ids(self) -> list[str]:
        """Return all selected question IDs in visual order."""
        return list(self._selection_state.selected_ids)

    def select_view(self, name: str) -> None:
        """Select a named view after a save or rename operation."""
        for index in range(self.views.count()):
            item = self.views.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                self.views.setCurrentRow(index)
                return

    def set_transient_filters(self, filters: QueryFilters) -> None:
        """Apply chart-driven or programmatic filters to the real controls."""
        self._query_filters = filters
        self._restore_filters(filters)
        self._update_active_filter()
        self.filters_changed.emit()

    def set_query_state(self, view_name: str, filters: QueryFilters) -> None:
        """Apply one complete visible query state and notify consumers once."""
        self._syncing = True
        self.search_timer.stop()
        try:
            if not self._select_view_row(view_name):
                raise ValueError(f"saved view not found: {view_name}")
            self._query_filters = filters
            self._set_filter_controls(filters)
        finally:
            self._syncing = False
        self._update_active_filter()
        self.filters_changed.emit()

    def clear_filters(self) -> None:
        """Restore the stable all-questions view and clear free-text search."""
        self.set_query_state("all", QueryFilters(limit=100_000))

    def set_theme(self, theme: ThemeName) -> None:
        """Refresh theme-dependent icons without rebuilding navigation."""
        self.theme_name = theme
        self.clear_filter.setIcon(icon("clear", theme))
        self.save_view.setIcon(icon("save", theme))
        self.bulk_add.setIcon(icon("add", theme, semantic="accent"))
        self.bulk_remove.setIcon(icon("remove", theme, semantic="accent"))
        self.facets.set_theme(theme)
        self.tags.set_theme(theme)

    def _update_active_filter(self, *_: object) -> None:
        try:
            filters = self.current_filters()
        except ValueError:
            return
        chips = self._chips(filters)
        self.filter_chips.set_chips(chips)
        current_item = cast(QListWidgetItem | None, self.views.currentItem())
        label = current_item.text() if current_item is not None else "全部题目"
        modified = self.current_view_is_modified(filters)
        if modified:
            label += " · 已修改"
        query = f" · 搜索“{filters.text}”" if filters.text else ""
        count = f"{self._result_total} 道题 · " if self._result_total is not None else ""
        visibility = " · 当前题目不在筛选结果中" if self._current_question_visible is False else ""
        loading = " · 搜索中…" if self._search_loading else ""
        summary = f"{count}当前筛选：{label}{query}{visibility}{loading}"
        self.active_filter.setText(summary)
        self.active_filter.setAccessibleName(summary)
        self.active_filter.setToolTip(summary)
        has_transient = bool(chips)
        self.clear_filter.setEnabled(has_transient or self.current_view() != "all")
        self.all_questions.setChecked(self.current_view() == "all" and not modified)
        current = self._view_definitions.get(self.current_view())
        self.view_actions.setEnabled(current is not None and (modified or not current.protected))
        QAccessible.updateAccessibility(
            QAccessibleEvent(self.active_filter, QAccessible.Event.NameChanged)
        )
        QAccessible.updateAccessibility(
            QAccessibleEvent(self.clear_filter, QAccessible.Event.StateChanged)
        )

    def _emit_view(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        del previous
        if current is not None:
            definition = self._view_definitions.get(str(current.data(Qt.ItemDataRole.UserRole)))
            if definition is not None:
                self._query_filters = definition.filters
                self._restore_filters(definition.filters)
            self._update_active_filter()
            self.view_changed.emit(str(current.data(Qt.ItemDataRole.UserRole)))

    def _restore_filters(self, filters: QueryFilters) -> None:
        self._syncing = True
        try:
            self._set_filter_controls(filters)
        finally:
            self._syncing = False

    def _set_filter_controls(self, filters: QueryFilters) -> None:
        self.search.setText(filters.text or "")
        self.facets.set_filters(filters)
        self.tags.set_filters(filters.topics, filters.excluded_topics, filters.topic_mode)

    def _search_updated(self, value: str) -> None:
        if self._syncing:
            return
        self._sync_query_from_controls()
        self._update_active_filter()
        self.search_timer.start()

    def _emit_debounced_search(self) -> None:
        self.search_changed.emit(self.search.text())

    def set_search_loading(self, loading: bool) -> None:
        """Show lightweight asynchronous search progress without hiding identity."""
        self._search_loading = loading
        self._update_active_filter()

    def _filters_changed(self, *_: object) -> None:
        if self._syncing:
            return
        self._sync_query_from_controls()
        self._update_active_filter()
        self.filters_changed.emit()

    def _toggle_facets(self, expanded: bool) -> None:
        self.facets.setVisible(expanded)
        self.filters_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced_scroll.setVisible(expanded)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _show_view_actions(self) -> None:
        view = self._view_definitions.get(self.current_view())
        if view is None:
            return
        menu = QMenu(self)
        restore = menu.addAction("恢复视图") if self.current_view_is_modified() else None
        if restore is not None and not view.protected:
            menu.addSeparator()
        rename = menu.addAction("重命名视图") if not view.protected else None
        delete = menu.addAction("删除视图") if not view.protected else None
        chosen = menu.exec(self.view_actions.mapToGlobal(self.view_actions.rect().bottomLeft()))
        if chosen == restore:
            self.restore_current_view()
        elif chosen == rename:
            self.rename_view_requested.emit(view.name)
        elif chosen == delete:
            self.delete_view_requested.emit(view.name)

    def restore_current_view(self) -> None:
        """Restore the selected saved snapshot without changing its identity."""
        view = self._view_definitions.get(self.current_view())
        if view is not None:
            self.set_query_state(view.name, view.filters)

    def current_view_is_modified(self, filters: QueryFilters | None = None) -> bool:
        """Return whether visible controls differ from the selected snapshot."""
        view = self._view_definitions.get(self.current_view())
        if view is None or view.name == "all":
            return False
        current = filters or self.current_filters()
        return current.semantic_values() != view.filters.semantic_values()

    def _select_view_row(self, name: str) -> bool:
        self.views.blockSignals(True)
        try:
            for index in range(self.views.count()):
                item = self.views.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == name:
                    self.views.setCurrentRow(index)
                    return True
            return False
        finally:
            self.views.blockSignals(False)

    @staticmethod
    def _visible_filter_values(filters: QueryFilters) -> dict[str, object]:
        return filters.semantic_values()

    def _sync_query_from_controls(self) -> None:
        projected = self.facets.filters(self.search.text().strip(), self.tags)
        self._query_filters = projected.model_copy(
            update={"limit": self._query_filters.limit, "offset": self._query_filters.offset}
        )

    def _remove_chip(self, key: str, value: str) -> None:
        self._syncing = True
        try:
            if key == "text":
                self.search.clear()
            elif key in {"topic", "excluded_topic"}:
                self.tags.remove(value)
            else:
                control = {
                    "status": self.facets.status,
                    "question_type": self.facets.question_type,
                    "subject": self.facets.subject,
                    "chapter": self.facets.chapter,
                    "language": self.facets.language,
                    "year": self.facets.year,
                    "difficulty_min": self.facets.difficulty_min,
                    "difficulty_max": self.facets.difficulty_max,
                }[key]
                if isinstance(control, ModernComboBox):
                    control.setCurrentIndex(0)
                else:
                    _line_edit(control).clear()
        finally:
            self._syncing = False
        self._filters_changed()

    @staticmethod
    def _chips(filters: QueryFilters) -> list[tuple[str, str, str]]:
        chips: list[tuple[str, str, str]] = []
        if filters.text:
            chips.append(("text", filters.text, f"搜索：{filters.text}"))
        chips.extend(("topic", topic, f"包含：{topic}") for topic in filters.topics)
        chips.extend(
            ("excluded_topic", topic, f"排除：{topic}") for topic in filters.excluded_topics
        )
        for key, value, label in (
            ("status", filters.status.value if filters.status else None, "状态"),
            (
                "question_type",
                filters.question_type.value if filters.question_type else None,
                "题型",
            ),
            ("subject", filters.subject, "学科"),
            ("chapter", filters.chapter, "章节"),
            ("language", filters.language, "语言"),
            ("year", filters.year, "年份"),
            ("difficulty_min", filters.difficulty_min, "最低难度"),
            ("difficulty_max", filters.difficulty_max, "最高难度"),
        ):
            if value is not None:
                chips.append((key, str(value), f"{label}：{value}"))
        return chips

    def _selection_changed(self) -> None:
        selected = tuple(
            str(item.data(Qt.ItemDataRole.UserRole)) for item in self.questions.selectedItems()
        )
        self._selection_state = self._selection_state.with_selection(selected)
        self._update_selection_bar()

    def _update_selection_bar(self) -> None:
        ids = self._selection_state.selected_ids
        enabled = bool(ids)
        self.bulk_add.setEnabled(enabled)
        self.bulk_remove.setEnabled(enabled)
        if not ids:
            summary = "未选择题目"
        else:
            visible = "、".join(ids[:2])
            suffix = f" 等 {len(ids)} 道题" if len(ids) > 2 else ""
            summary = f"已选择 {len(ids)} 道题 · {visible}{suffix}"
        self.selection_summary.setText(summary)
        self.selection_summary.setToolTip(
            "、".join(ids) if ids else "批量操作仅作用于明确选择的题目"
        )

    def _emit_question(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is not None:
            self.question_selected.emit(str(current.data(Qt.ItemDataRole.UserRole)))


class FriendlyValueEdit(QLineEdit):
    """Show a localized label at rest while retaining an editable machine value."""

    def __init__(self, labels: dict[str, str]) -> None:
        super().__init__()
        self._labels = labels
        self._raw_value = ""
        self.textEdited.connect(self._remember_edit)

    def set_raw_value(self, value: str) -> None:
        self._raw_value = value
        self._show_friendly_value()

    def raw_value(self) -> str:
        return self.text() if self.hasFocus() else self._raw_value

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.setText(self._raw_value)
        super().focusInEvent(event)
        self.selectAll()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self._raw_value = self.text().strip()
        self._show_friendly_value()
        super().focusOutEvent(event)

    def _remember_edit(self, value: str) -> None:
        self._raw_value = value

    def _show_friendly_value(self) -> None:
        label = self._labels.get(self._raw_value)
        self.setText(f"{label}  ·  {self._raw_value}" if label else self._raw_value)


class TopicTagEditor(QWidget):
    """Small removable-topic editor with keyboard completion."""

    topics_changed = Signal()
    pending_topic_created = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("topicTagEditor")
        self._topics: list[str] = []
        self._suggestions: set[str] = set(_TOPIC_SUGGESTIONS)
        self._registry: dict[str, TagUsage] = {}
        self._identity_to_slug: dict[str, str] = {}
        self._completion_to_slug: dict[str, str] = {}
        self.tags = QWidget()
        self.tags_layout = QHBoxLayout(self.tags)
        self.tags_layout.setContentsMargins(0, 0, 0, 0)
        self.tags_layout.setSpacing(METRICS.space_1)
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入标签后按 Enter")
        self.input.setAccessibleName("添加标签")
        self._completion_model = QStringListModel(sorted(self._suggestions), self)
        self.completer = QCompleter(self._completion_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.input.setCompleter(self.completer)
        self.completer.activated.connect(self._completion_activated)
        self.input.textEdited.connect(self.topics_changed.emit)
        self.input.returnPressed.connect(self._accept_input)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_1)
        layout.addWidget(self.tags)
        layout.addWidget(self.input)

    def set_topics(self, topics: list[str]) -> None:
        self.input.clear()
        self._topics = list(dict.fromkeys(topic.strip() for topic in topics if topic.strip()))
        self._suggestions.update(self._topics)
        self._completion_model.setStringList(sorted(self._suggestions))
        self._rebuild_tags()

    def set_registry(self, rows: list[TagUsage]) -> None:
        """Use canonical taxonomy identities and counts for completion."""
        self._registry = {row.slug: row for row in rows}
        self._identity_to_slug = {}
        self._completion_to_slug = {}
        completions: list[str] = []
        for row in sorted(rows, key=lambda item: (-item.count, item.slug)):
            metadata = row.metadata
            display = metadata.name_zh if metadata and metadata.name_zh else row.slug
            aliases = metadata.aliases if metadata is not None else []
            alias_text = f" · {' / '.join(aliases)}" if aliases else ""
            completion = f"{display} · {row.slug} · {row.count}{alias_text}"
            completions.append(completion)
            self._completion_to_slug[completion] = row.slug
            identities = [row.slug]
            if metadata is not None:
                identities.extend(
                    value
                    for value in (metadata.name_zh, metadata.name_en, *metadata.aliases)
                    if value
                )
            for identity in identities:
                self._identity_to_slug[identity.casefold()] = row.slug
        self._suggestions.update(self._registry)
        self._completion_model.setStringList(completions)
        self._rebuild_tags()

    def topics(self) -> list[str]:
        pending = [self._canonical_topic(value) for value in self.input.text().split(",")]
        return [
            *self._topics,
            *(topic for topic in pending if topic and topic not in self._topics),
        ]

    def discard_topic(self, topic: str) -> None:
        """Remove a just-proposed topic after synonym confirmation is rejected."""
        if topic in self._topics:
            self._remove_topic(topic)

    def _accept_input(self) -> None:
        additions = [value.strip() for value in self.input.text().split(",")]
        changed = False
        for topic in additions:
            canonical = self._canonical_topic(topic)
            if canonical and canonical not in self._topics:
                self._topics.append(canonical)
                self._suggestions.add(canonical)
                changed = True
                if canonical not in self._registry:
                    self.pending_topic_created.emit(canonical)
        self.input.clear()
        if changed:
            self._completion_model.setStringList(sorted(self._suggestions))
            self._rebuild_tags()
            self.topics_changed.emit()

    def _remove_topic(self, topic: str) -> None:
        self._topics.remove(topic)
        self._rebuild_tags()
        self.topics_changed.emit()

    def _completion_activated(self, value: str) -> None:
        slug = self._completion_to_slug.get(value)
        if slug is not None:
            self.input.setText(slug)
            self._accept_input()

    def _canonical_topic(self, value: str) -> str | None:
        normalized = value.strip()
        if not normalized:
            return None
        resolved = self._identity_to_slug.get(normalized.casefold())
        if resolved is not None:
            return resolved
        try:
            return normalize_tag_slug(normalized)
        except ValueError:
            return None

    def _rebuild_tags(self) -> None:
        while self.tags_layout.count():
            item = cast(QLayoutItem | None, self.tags_layout.takeAt(0))
            if item is None:
                break
            widget = cast(QWidget | None, item.widget())
            if widget is not None:
                widget.deleteLater()
        for topic in self._topics:
            tag = QToolButton()
            tag.setObjectName("topicTag")
            usage = self._registry.get(topic)
            pending = usage is None or (
                usage.metadata is not None and usage.metadata.status.value == "pending"
            )
            suffix = " · 待整理" if pending else ""
            tag.setText(f"{topic}{suffix}  ×")
            tag.setToolTip(f"移除标签 {topic}")
            tag.setAccessibleName(f"移除标签 {topic}")
            tag.clicked.connect(lambda checked=False, value=topic: self._remove_topic(value))
            self.tags_layout.addWidget(tag)
        self.tags_layout.addStretch()


class MetadataPanel(QWidget):
    """Dense two-column property form for daily review."""

    metadata_changed = Signal()

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self.setObjectName("metadataPanel")
        self.title = QLineEdit()
        self.subject = FriendlyValueEdit(_SUBJECT_LABELS)
        self.chapter = QLineEdit()
        self.topics = TopicTagEditor()
        self.question_type = _friendly_combo(theme, QuestionType, _QUESTION_TYPE_LABELS)
        self.status = _friendly_combo(theme, QuestionStatus, _QUESTION_STATUS_LABELS)
        self.difficulty = ModernSpinBox(theme)
        self.difficulty.setRange(1, 5)
        self.language = FriendlyValueEdit(_LANGUAGE_LABELS)
        self.difficulty_caption = QLabel()
        self.difficulty_caption.setObjectName("fieldHint")
        self.ai_difficulty_hint = QLabel("AI 建议值，需人工确认")
        self.ai_difficulty_hint.setObjectName("statusWarning")
        self.ai_difficulty_hint.setVisible(False)
        self._build_layout()
        self._wire_changes()

    def _build_layout(self) -> None:
        layout = QGridLayout(self)
        layout.setContentsMargins(METRICS.space_3, METRICS.space_3, METRICS.space_3, 20)
        layout.setHorizontalSpacing(METRICS.space_2)
        layout.setVerticalSpacing(METRICS.space_1)
        layout.addWidget(_section_label("核心信息"), 0, 0, 1, 2)
        row = _add_field(layout, 1, 0, "标题", self.title, column_span=2)
        _add_field(layout, row, 0, "学科", self.subject)
        _add_field(layout, row, 1, "章节", self.chapter)
        row += 2
        row = _add_field(layout, row, 0, "标签", self.topics, column_span=2)
        layout.addWidget(_section_label("分类与审阅"), row, 0, 1, 2)
        row += 1
        _add_field(layout, row, 0, "题型", self.question_type)
        _add_field(layout, row, 1, "状态", self.status)
        row += 2
        _add_field(layout, row, 0, "难度", self.difficulty)
        _add_field(layout, row, 1, "语言", self.language)
        row += 2
        layout.addWidget(self.difficulty_caption, row, 0)
        layout.addWidget(self.ai_difficulty_hint, row, 1)
        layout.setRowStretch(row + 1, 1)

    def _wire_changes(self) -> None:
        for field in (self.title, self.subject, self.chapter, self.language):
            field.textEdited.connect(self._metadata_text_changed)
        self.topics.topics_changed.connect(self.metadata_changed.emit)
        self.question_type.currentIndexChanged.connect(self._metadata_index_changed)
        self.status.currentIndexChanged.connect(self._metadata_index_changed)
        self.difficulty.valueChanged.connect(self._difficulty_changed)

    def _metadata_text_changed(self, _value: str) -> None:
        self.metadata_changed.emit()

    def _metadata_index_changed(self, _index: int) -> None:
        self.metadata_changed.emit()

    def _difficulty_changed(self, value: int) -> None:
        self.difficulty_caption.setText(f"{value} / 5 · {_DIFFICULTY_LABELS[value]}")
        self.metadata_changed.emit()

    def set_theme(self, theme: ThemeName) -> None:
        self.theme_name = theme
        self.question_type.set_theme(theme)
        self.status.set_theme(theme)
        self.difficulty.set_theme(theme)

    def set_taxonomy(self, rows: list[TagUsage]) -> None:
        """Refresh canonical topic autocomplete and pending-state labels."""
        self.topics.set_registry(rows)

    def load_document(self, document: DesktopQuestionDocument) -> None:
        question = document.question
        self.title.setText(question.title)
        self.subject.set_raw_value(question.subject)
        self.chapter.setText(question.chapter or "")
        self.topics.set_topics(question.topics)
        _select_combo_data(self.question_type, question.type.value)
        _select_combo_data(self.status, question.status.value)
        self.difficulty.setValue(question.difficulty)
        self.language.set_raw_value(question.language)
        source_kind = question.source.type.casefold()
        self.ai_difficulty_hint.setVisible(source_kind in {"ai", "generated", "inferred"})
        self._difficulty_changed(question.difficulty)

    def set_values(self, values: dict[str, object]) -> None:
        self.title.setText(str(values["title"]))
        self.subject.set_raw_value(str(values["subject"]))
        self.chapter.setText(str(values["chapter"]))
        topics = values["topics"]
        self.topics.set_topics(
            [str(topic) for topic in cast(list[object], topics)]
            if isinstance(topics, list)
            else str(topics).split(",")
        )
        _select_combo_data(self.question_type, str(values["type"]))
        _select_combo_data(self.status, str(values["status"]))
        self.difficulty.setValue(int(str(values["difficulty"])))
        self.language.set_raw_value(str(values["language"]))

    def values(self) -> dict[str, object]:
        return {
            "title": self.title.text(),
            "subject": self.subject.raw_value(),
            "chapter": self.chapter.text(),
            "topics": self.topics.topics(),
            "type": str(self.question_type.currentData()),
            "status": str(self.status.currentData()),
            "difficulty": self.difficulty.value(),
            "language": self.language.raw_value(),
        }


class InspectorSummary(QWidget):
    """Fixed identity and review-state summary above inspector tabs."""

    copy_requested = Signal(str)

    def __init__(self, theme: ThemeName) -> None:
        super().__init__()
        self.theme_name = theme
        self.question_id = ""
        self.title = QLabel("尚未选择题目")
        self.title.setObjectName("inspectorTitle")
        self.title.setWordWrap(True)
        self.identifier = QLabel("—")
        self.identifier.setObjectName("inspectorId")
        self.copy = QToolButton()
        self.copy.setObjectName("compactIconButton")
        self.copy.setToolTip("复制题目 ID")
        self.copy.setAccessibleName("复制题目 ID")
        self.copy.clicked.connect(lambda: self.copy_requested.emit(self.question_id))
        self.status = QLabel("未载入")
        self.validation = QLabel("未校验")
        self.asset_count = QLabel("资产 0")
        self.warning = QLabel()
        self.warning.setObjectName("summaryWarning")
        self.warning.setWordWrap(True)
        self.warning.setVisible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(METRICS.space_3, METRICS.space_3, METRICS.space_3, 10)
        layout.setSpacing(METRICS.space_1)
        layout.addWidget(self.title)
        identity = QHBoxLayout()
        identity.addWidget(self.identifier)
        identity.addWidget(self.copy)
        identity.addStretch()
        layout.addLayout(identity)
        badges = QHBoxLayout()
        for badge in (self.status, self.validation, self.asset_count):
            badge.setObjectName("summaryBadge")
            badges.addWidget(badge)
        badges.addStretch()
        layout.addLayout(badges)
        layout.addWidget(self.warning)
        self.set_theme(theme)

    def set_theme(self, theme: ThemeName) -> None:
        self.theme_name = theme
        self.copy.setIcon(icon("copy", theme))

    def load_document(self, document: DesktopQuestionDocument) -> None:
        question = document.question
        self.question_id = question.id
        self.title.setText(question.title)
        self.identifier.setText(question.id)
        self.status.setText(
            _QUESTION_STATUS_LABELS.get(question.status.value, question.status.value)
        )
        self.validation.setText("结构有效")
        self.validation.setProperty("state", "success")
        self.asset_count.setText(f"资产 {len(document.asset_items)}")
        self._refresh_style(self.validation)

    def set_validation(self, ok: bool, errors: int = 0) -> None:
        self.validation.setText("校验通过" if ok else f"{errors} 项错误")
        self.validation.setProperty("state", "success" if ok else "error")
        self._refresh_style(self.validation)

    def set_warning(self, messages: list[str]) -> None:
        self.warning.setText(" · ".join(messages))
        self.warning.setVisible(bool(messages))

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class AssetCard(QFrame):
    """Compact document-object card for one logical asset."""

    action_requested = Signal(str, str)
    theme_name: ThemeName

    def __init__(self, item: DesktopAssetItem, theme: ThemeName) -> None:
        super().__init__()
        if item.manifest is None:
            raise ValueError("logical asset item must include its manifest")
        self.item = item
        self.asset = item.manifest
        self.theme_name = theme
        self.setObjectName("assetCard")
        self.thumbnail = QLabel()
        self.thumbnail.setObjectName("assetThumbnail")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(74, 58)
        self._load_thumbnail(item.preview_path)
        self.representations = QWidget()
        self.representations.setVisible(False)
        self.representations.setObjectName("representationsPanel")
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(METRICS.space_2, METRICS.space_2, METRICS.space_2, 10)
        layout.setSpacing(METRICS.space_2)
        layout.addLayout(self._overview_layout())
        layout.addLayout(self._action_layout())
        toggle = self._representation_toggle()
        layout.addWidget(toggle)
        self._build_representation_rows()
        layout.addWidget(self.representations)

    def _overview_layout(self) -> QHBoxLayout:
        overview = QHBoxLayout()
        overview.addWidget(self.thumbnail)
        detail = QVBoxLayout()
        name = QLabel(self.asset.asset_id)
        name.setObjectName("assetName")
        detail.addWidget(name)
        status = _ASSET_STATUS_LABELS.get(self.asset.status.value, self.asset.status.value)
        meta = QLabel(f"{self.asset.role}  ·  {status}")
        meta.setObjectName("fieldHint")
        detail.addWidget(meta)
        detail.addWidget(QLabel(f"编辑：{self.asset.preferred_editor or '未设置'}"))
        detail.addWidget(QLabel(f"渲染：{self.asset.preferred_render or '未设置'}"))
        overview.addLayout(detail, 1)
        return overview

    def _action_layout(self) -> QHBoxLayout:
        actions = QHBoxLayout()
        actions.setSpacing(METRICS.space_1)
        capabilities = self.item.capabilities
        has_ipe_editor = any(
            item.editable and item.format.value == "ipe" for item in self.asset.representations
        )
        for label, action_name, enabled, unavailable_reason in (
            (
                "用 Ipe 编辑" if has_ipe_editor else "编辑",
                "edit",
                capabilities.edit,
                "该资产没有可编辑表示",
            ),
            ("替换", "replace-file", capabilities.replace, "该资产不能替换"),
            ("重新渲染", "render", capabilities.render, "该资产没有可渲染的 Ipe 源"),
        ):
            button = QPushButton(label)
            button.setObjectName("compactButton")
            button.setProperty("assetAction", action_name)
            button.setAccessibleName(f"{self.asset.asset_id}：{label}")
            button.setEnabled(enabled)
            if not enabled:
                button.setToolTip(unavailable_reason)
            button.clicked.connect(
                lambda checked=False, aid=self.asset.asset_id, name=action_name: (
                    self.action_requested.emit(aid, name)
                )
            )
            actions.addWidget(button)
        more = QToolButton()
        more.setObjectName("compactIconButton")
        more.setIcon(icon("more", self.theme_name))
        more.setToolTip("更多资产操作")
        more.setAccessibleName("更多资产操作")
        menu = _asset_more_menu(
            more,
            self.asset.asset_id,
            self._emit_action,
            self.theme_name,
            capabilities,
        )
        more.setMenu(menu)
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        actions.addWidget(more)
        return actions

    def _representation_toggle(self) -> QToolButton:
        toggle = QToolButton()
        toggle.setObjectName("representationToggle")
        toggle.setText(f"多表示 {len(self.asset.representations)}")
        toggle.setCheckable(True)
        toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toggle.setIcon(icon("chevron-down", self.theme_name))
        toggle.toggled.connect(partial(self._toggle_representations, toggle))
        return toggle

    def _build_representation_rows(self) -> None:
        representations_layout = QVBoxLayout(self.representations)
        representations_layout.setContentsMargins(METRICS.space_2, 0, 0, 0)
        representations_layout.setSpacing(METRICS.space_1)
        for item in self.asset.representations:
            suffix = " · 已过期" if item.stale else ""
            row = QLabel(f"{item.representation_id}  ·  {item.format.value}{suffix}")
            row.setObjectName("fieldHint")
            representations_layout.addWidget(row)

    def _toggle_representations(self, button: QToolButton, visible: bool) -> None:
        self.representations.setVisible(visible)
        button.setIcon(icon("chevron-up" if visible else "chevron-down", self.theme_name))

    def _emit_action(self, asset_id: str, action: str) -> None:
        self.action_requested.emit(asset_id, action)

    def _load_thumbnail(self, preview_path: str | None) -> None:
        if preview_path is None:
            self.thumbnail.setPixmap(icon("question", self.theme_name).pixmap(26, 26))
            return
        pixmap = QPixmap(preview_path)
        if pixmap.isNull():
            self.thumbnail.setPixmap(icon("question", self.theme_name).pixmap(26, 26))
            return
        self.thumbnail.setPixmap(
            pixmap.scaled(
                self.thumbnail.size() - QSize(8, 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class LegacyAssetCard(QFrame):
    """Inspectable card for one unmanaged local, external, or invalid reference."""

    action_requested = Signal(str, str)

    def __init__(
        self,
        item: DesktopAssetItem,
        theme: ThemeName,
    ) -> None:
        super().__init__()
        self.item = item
        reference = item.reference
        self.setObjectName("assetCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(METRICS.space_2, METRICS.space_2, METRICS.space_2, 10)
        row = QHBoxLayout()
        preview = QLabel()
        preview.setObjectName("assetThumbnail")
        preview.setFixedSize(74, 58)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = Path(item.preview_path) if item.preview_path is not None else None
        pixmap = QPixmap(str(path)) if path is not None else QPixmap()
        preview.setPixmap(
            pixmap.scaled(66, 50, Qt.AspectRatioMode.KeepAspectRatio)
            if not pixmap.isNull()
            else icon("question", theme).pixmap(26, 26)
        )
        row.addWidget(preview)
        copy = QVBoxLayout()
        name = QLabel(Path(reference).name)
        name.setObjectName("assetName")
        copy.addWidget(name)
        state_text, state_name = _unmanaged_reference_state(item)
        state = QLabel(state_text)
        state.setObjectName(state_name)
        copy.addWidget(state)
        reference_label = QLabel(reference)
        reference_label.setObjectName("fieldHint")
        reference_label.setWordWrap(True)
        copy.addWidget(reference_label)
        row.addLayout(copy, 1)
        layout.addLayout(row)
        actions = QHBoxLayout()
        for label, action in _unmanaged_reference_actions(item):
            button = QPushButton(label)
            button.setObjectName("compactButton")
            button.clicked.connect(
                lambda checked=False, value=reference, name=action: self.action_requested.emit(
                    value, name
                )
            )
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)


class AssetPanel(QScrollArea):
    """Scrollable collection of logical and legacy image objects."""

    action_requested = Signal(str, str)
    legacy_action_requested = Signal(str, str)
    add_requested = Signal()
    theme_name: ThemeName

    def __init__(
        self, project_root: Path | None, assets_root: Path | None, theme: ThemeName
    ) -> None:
        super().__init__()
        del project_root, assets_root
        self.theme_name = theme
        self._document: DesktopQuestionDocument | None = None
        self.setWidgetResizable(True)
        self.setAccessibleName("图形资产")
        self.content = QWidget()
        self.layout_ = QVBoxLayout(self.content)
        self.layout_.setContentsMargins(METRICS.space_3, METRICS.space_3, METRICS.space_3, 20)
        self.layout_.setSpacing(METRICS.space_2)
        self.setWidget(self.content)

    def load_document(self, document: DesktopQuestionDocument) -> None:
        self._document = document
        _clear_layout(self.layout_)
        for item in document.asset_items:
            if item.kind == "logical" and item.manifest is not None:
                logical_card = AssetCard(item, self.theme_name)
                logical_card.action_requested.connect(self.action_requested.emit)
                self.layout_.addWidget(logical_card)
                continue
            reference_card = LegacyAssetCard(item, self.theme_name)
            reference_card.action_requested.connect(self.legacy_action_requested.emit)
            self.layout_.addWidget(reference_card)
        if not document.asset_items:
            empty = _empty_state(
                "暂无图形资产",
                "可从文件添加，或把图片拖到预览中的插入位置。",
                "添加图片…",
            )
            empty.clicked.connect(self.add_requested.emit)
            self.layout_.addWidget(empty)
        self.layout_.addStretch()

    def set_theme(self, theme: ThemeName) -> None:
        self.theme_name = theme
        if self._document is not None:
            self.load_document(self._document)


class SourcePanel(QScrollArea):
    """Human-readable provenance form with raw data kept secondary."""

    changed = Signal()
    theme_name: ThemeName

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self.setWidgetResizable(True)
        self.setAccessibleName("来源信息")
        self.content = QWidget()
        self.form = QGridLayout(self.content)
        self.form.setContentsMargins(METRICS.space_3, METRICS.space_3, METRICS.space_3, 20)
        self.form.setHorizontalSpacing(METRICS.space_2)
        self.form.setVerticalSpacing(METRICS.space_2)
        self.inputs = {"type": QLineEdit(), "reference": QLineEdit()}
        self.inputs["type"].setAccessibleName("来源类型")
        self.inputs["type"].setPlaceholderText("例如 manual、book、paper")
        self.inputs["reference"].setAccessibleName("来源文件或资料")
        self.inputs["reference"].setPlaceholderText("文件、书目、试卷及可定位信息")
        self.fields = {name: _readonly_value() for name in ("year", "number", "page", "method")}
        for row, (label, key) in enumerate(
            (
                ("来源类型", "type"),
                ("文件 / 资料", "reference"),
                ("年份", "year"),
                ("题号", "number"),
                ("页码", "page"),
                ("提取方式", "method"),
            )
        ):
            field_label = QLabel(label)
            field_label.setObjectName("fieldLabel")
            self.form.addWidget(field_label, row, 0)
            control = self.inputs[key] if key in self.inputs else self.fields[key]
            self.form.addWidget(control, row, 1)
        self.missing = _empty_state(
            "来源信息不完整", "请直接填写上方来源类型与可定位资料。", "填写来源"
        )
        self.missing.clicked.connect(self.inputs["reference"].setFocus)
        self.form.addWidget(self.missing, 6, 0, 1, 2)
        self.raw_toggle = QToolButton()
        self.raw_toggle.setObjectName("representationToggle")
        self.raw_toggle.setText("查看原始数据")
        self.raw_toggle.setCheckable(True)
        self.raw_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.raw_toggle.setIcon(icon("chevron-down", theme))
        self.form.addWidget(self.raw_toggle, 7, 0, 1, 2)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setMaximumHeight(180)
        self.raw.setVisible(False)
        self.raw.setAccessibleName("原始来源数据")
        self.form.addWidget(self.raw, 8, 0, 1, 2)
        self.form.setRowStretch(9, 1)
        self.raw_toggle.toggled.connect(self._toggle_raw)
        for field in self.inputs.values():
            field.textChanged.connect(self.changed.emit)
        self.setWidget(self.content)

    def load_document(self, document: DesktopQuestionDocument) -> None:
        source = document.question.source.model_dump(mode="json")
        reference = str(source.get("reference") or "")
        year = next(iter(re.findall(r"(?:19|20)\d{2}", reference)), "")
        page = _first_provenance_value(document.assets, ("matched_page", "page", "page_number"))
        source_type = str(source.get("type") or "")
        for key, value in (("type", source_type), ("reference", reference)):
            self.inputs[key].blockSignals(True)
            self.inputs[key].setText(value)
            self.inputs[key].blockSignals(False)
        values = {
            "year": year,
            "number": _question_number(reference),
            "page": page,
            "method": _source_method_label(document.assets),
        }
        for key, value in values.items():
            self.fields[key].setText(value or "未记录")
            self.fields[key].setProperty("missing", not bool(value))
            _refresh_widget_style(self.fields[key])
        self.missing.setVisible(not bool(reference))
        self.raw.setPlainText(json.dumps(source, ensure_ascii=False, indent=2))

    def values(self) -> dict[str, str | None]:
        """Return the persisted Source model projection."""
        return {
            "type": self.inputs["type"].text().strip(),
            "reference": self.inputs["reference"].text().strip() or None,
        }

    def set_theme(self, theme: ThemeName) -> None:
        self.theme_name = theme
        self.raw_toggle.setIcon(
            icon("chevron-up" if self.raw_toggle.isChecked() else "chevron-down", theme)
        )

    def _toggle_raw(self, visible: bool) -> None:
        self.raw.setVisible(visible)
        self.raw_toggle.setIcon(icon("chevron-up" if visible else "chevron-down", self.theme_name))


class HistoryPanel(QScrollArea):
    """Compact chronological activity timeline."""

    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setAccessibleName("修改历史")
        self.content = QWidget()
        self.layout_ = QVBoxLayout(self.content)
        self.layout_.setContentsMargins(METRICS.space_3, METRICS.space_3, METRICS.space_3, 20)
        self.layout_.setSpacing(0)
        self.setWidget(self.content)

    def load_document(self, document: DesktopQuestionDocument) -> None:
        _clear_layout(self.layout_)
        if not document.history:
            empty = _empty_state(
                "尚无历史记录",
                "保存题目或处理图形资产后，变更会按时间显示在这里。",
                "返回基础属性",
            )
            empty.clicked.connect(self.back_requested.emit)
            self.layout_.addWidget(empty)
        for event in reversed(document.history):
            row = QWidget()
            row.setObjectName("timelineRow")
            item = QHBoxLayout(row)
            item.setContentsMargins(0, METRICS.space_2, 0, METRICS.space_2)
            bullet = QLabel("●")
            bullet.setObjectName("timelineBullet")
            bullet.setAlignment(Qt.AlignmentFlag.AlignTop)
            item.addWidget(bullet)
            copy = QVBoxLayout()
            copy.setSpacing(METRICS.space_1)
            title = QLabel(_history_operation_label(event.operation))
            title.setObjectName("timelineTitle")
            copy.addWidget(title)
            timestamp = _format_timestamp(event.timestamp)
            fields = "、".join(
                _history_field_label(field) for field in getattr(event, "fields", [])
            )
            detail = f" · {fields}" if fields else ""
            asset = f" · {event.asset_id}" if event.asset_id else ""
            source = getattr(event, "source", "图形资产")
            metadata = QLabel(f"{timestamp} · {source}{detail}{asset}")
            metadata.setWordWrap(True)
            if _parse_timestamp(event.timestamp) is None:
                metadata.setObjectName("statusWarning")
                metadata.setToolTip("历史时间格式无效，已保留原始值")
            copy.addWidget(metadata)
            item.addLayout(copy, 1)
            self.layout_.addWidget(row)
        self.layout_.addStretch()


class DetailDrawer(QDockWidget):
    """Resizable, persistent desktop Inspector for the current question."""

    asset_activated = Signal(str)
    asset_action_requested = Signal(str, str)
    legacy_asset_action_requested = Signal(str, str)
    add_asset_requested = Signal()
    save_requested = Signal()
    restore_requested = Signal()
    theme_name: ThemeName

    def __init__(
        self,
        theme: ThemeName = "light",
        *,
        project_root: Path | None = None,
        assets_root: Path | None = None,
    ) -> None:
        super().__init__("题目详情")
        self.theme_name = theme
        self._needs_redraw = False
        self._source_missing = False
        self._persist_width = False
        self.setObjectName("detailDrawer")
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(280)
        self.setMaximumWidth(460)
        self.summary = InspectorSummary(theme)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("inspectorTabs")
        self.metadata = MetadataPanel(theme)
        self.assets = AssetPanel(project_root, assets_root, theme)
        self.source = SourcePanel(theme)
        self.history = HistoryPanel()
        self._add_scroll_tab(self.metadata, "基础属性")
        self.tabs.addTab(self.assets, "资产 0")
        self.tabs.addTab(self.source, "来源")
        self.tabs.addTab(self.history, "历史 0")
        self.action_bar = _inspector_action_bar()
        self.action_bar.setVisible(False)
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.summary)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.action_bar)
        self.setWidget(wrapper)
        self._connect_actions()

    def preferred_width(self) -> int:
        value = QSettings().value("studio/detailDrawerWidth", 340)
        try:
            return max(280, min(460, int(str(value))))
        except ValueError:
            return 340

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._persist_width and 280 <= event.size().width() <= 460 and self.isVisible():
            QSettings().setValue("studio/detailDrawerWidth", event.size().width())

    def enable_width_persistence(self) -> None:
        self._persist_width = True

    def _add_scroll_tab(self, widget: QWidget, title: str) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.tabs.addTab(scroll, title)

    def _connect_actions(self) -> None:
        self.assets.action_requested.connect(self.asset_action_requested.emit)
        self.assets.legacy_action_requested.connect(self.legacy_asset_action_requested.emit)
        self.assets.add_requested.connect(self.add_asset_requested.emit)
        self.history.back_requested.connect(lambda: self.tabs.setCurrentIndex(0))
        self.summary.copy_requested.connect(self._copy_id)
        restore = self.action_bar.findChild(QPushButton, "restoreChanges")
        save = self.action_bar.findChild(QPushButton, "saveChanges")
        if restore is not None:
            restore.clicked.connect(self.restore_requested.emit)
        if save is not None:
            save.clicked.connect(self.save_requested.emit)

    def set_theme(self, theme: ThemeName) -> None:
        self.theme_name = theme
        self.metadata.set_theme(theme)
        self.summary.set_theme(theme)
        self.assets.set_theme(theme)
        self.source.set_theme(theme)
        self.tabs.setTabIcon(
            1,
            icon("warning", theme, semantic="warning") if self._needs_redraw else QIcon(),
        )
        self.tabs.setTabIcon(
            2,
            icon("warning", theme, semantic="warning") if self._source_missing else QIcon(),
        )

    def load_document(self, document: DesktopQuestionDocument) -> None:
        self.metadata.load_document(document)
        self.summary.load_document(document)
        self.assets.load_document(document)
        self.source.load_document(document)
        self.history.load_document(document)
        count = len(document.asset_items)
        self.tabs.setTabText(1, f"资产 {count}")
        self.tabs.setTabText(2, "来源")
        self.tabs.setTabText(3, f"历史 {len(document.history)}")
        redraw = any(asset.status.value == "needs_redraw" for asset in document.assets)
        has_asset_warning = any(item.diagnostic is not None for item in document.asset_items)
        self._needs_redraw = redraw or has_asset_warning
        self._source_missing = not bool(document.question.source.reference)
        self.tabs.setTabIcon(
            1,
            icon("warning", self.theme_name, semantic="warning") if self._needs_redraw else QIcon(),
        )
        self.tabs.setTabIcon(
            2,
            icon("warning", self.theme_name, semantic="warning")
            if not document.question.source.reference
            else QIcon(),
        )
        self.set_dirty_state(0, preview_pending=False, needs_redraw=redraw)

    def refresh_asset_state(self, document: DesktopQuestionDocument) -> None:
        """Refresh asset-derived tabs without replacing live metadata edits."""
        self.assets.load_document(document)
        self.source.load_document(document)
        self.history.load_document(document)
        count = len(document.asset_items)
        redraw = any(asset.status.value == "needs_redraw" for asset in document.assets)
        has_asset_warning = any(item.diagnostic is not None for item in document.asset_items)
        self._needs_redraw = redraw or has_asset_warning
        self._source_missing = not bool(document.question.source.reference)
        self.summary.asset_count.setText(f"资产 {count}")
        self.tabs.setTabText(1, f"资产 {count}")
        self.tabs.setTabText(3, f"历史 {len(document.history)}")
        self.tabs.setTabIcon(
            1,
            icon("warning", self.theme_name, semantic="warning") if self._needs_redraw else QIcon(),
        )
        self.tabs.setTabIcon(
            2,
            icon("warning", self.theme_name, semantic="warning")
            if self._source_missing
            else QIcon(),
        )

    def values(self) -> dict[str, object]:
        values = self.metadata.values()
        values["source"] = self.source.values()
        return values

    def set_dirty_state(
        self,
        changed_fields: int,
        *,
        preview_pending: bool,
        needs_redraw: bool | None = None,
    ) -> None:
        messages: list[str] = []
        if changed_fields:
            messages.append(f"{changed_fields} 项修改尚未保存")
        if preview_pending:
            messages.append("预览待刷新")
        if needs_redraw is None:
            needs_redraw = self._needs_redraw
        if needs_redraw:
            messages.append("图形待重绘")
        self.summary.set_warning(messages)
        label = self.action_bar.findChild(QLabel, "changeCount")
        if label is not None:
            label.setText(f"{changed_fields} 项修改")
        self.action_bar.setVisible(changed_fields > 0)

    def set_validation(self, ok: bool, errors: int = 0) -> None:
        self.summary.set_validation(ok, errors)

    @staticmethod
    def _copy_id(question_id: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(question_id)


class EmptyState(QFrame):
    """Small explanatory empty state with one useful next action."""

    clicked = Signal()

    def __init__(self, title: str, detail: str, action: str) -> None:
        super().__init__()
        self.setObjectName("inspectorEmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_3, METRICS.space_4, METRICS.space_3, METRICS.space_4
        )
        layout.setSpacing(METRICS.space_2)
        heading = QLabel(title)
        heading.setObjectName("emptyStateTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        copy = QLabel(detail)
        copy.setObjectName("fieldHint")
        copy.setWordWrap(True)
        copy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copy)
        button = QPushButton(action)
        button.setObjectName("compactButton")
        button.clicked.connect(self.clicked.emit)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)


def _friendly_combo(
    theme: ThemeName,
    enum_type: type[QuestionType] | type[QuestionStatus],
    labels: dict[str, str],
) -> ModernComboBox:
    combo = ModernComboBox(theme)
    for item in enum_type:
        combo.addItem(labels.get(item.value, item.value), item.value)
    return combo


def _select_combo_data(combo: ModernComboBox, value: str | None) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(max(0, index))


def _select_or_add_combo_data(combo: ModernComboBox, value: str | None) -> None:
    """Project a valid query value without dropping values absent from this bank."""
    if value is None:
        combo.setCurrentIndex(0)
        return
    index = combo.findData(value)
    if index < 0:
        combo.addItem(value, value)
        index = combo.findData(value)
    combo.setCurrentIndex(index)


def _set_combo_choices(combo: ModernComboBox, choices: list[str]) -> None:
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("不限", None)
    for value in choices:
        combo.addItem(value, value)
    index = combo.findData(current)
    combo.setCurrentIndex(max(0, index))
    combo.blockSignals(False)


def _combo_optional(combo: ModernComboBox) -> str | None:
    value = combo.currentData()
    return str(value) if value is not None else None


def _line_edit(control: QWidget) -> QLineEdit:
    """Narrow a heterogeneous facet control at the shared UI boundary."""
    if not isinstance(control, QLineEdit):
        raise TypeError("facet control is not a line edit")
    return control


def _combo_optional_int(combo: ModernComboBox) -> int | None:
    value = _combo_optional(combo)
    return int(value) if value is not None else None


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    return label


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("inspectorSectionLabel")
    return label


def _add_field(
    layout: QGridLayout,
    row: int,
    column: int,
    label_text: str,
    control: QWidget,
    *,
    column_span: int = 1,
) -> int:
    label = QLabel(label_text)
    label.setObjectName("fieldLabel")
    label.setBuddy(control)
    control.setAccessibleName(label_text)
    layout.addWidget(label, row, column, 1, column_span)
    layout.addWidget(control, row + 1, column, 1, column_span)
    return row + 2


def _empty_state(title: str, detail: str, action: str) -> EmptyState:
    return EmptyState(title, detail, action)


def _inspector_action_bar() -> QFrame:
    bar = QFrame()
    bar.setObjectName("inspectorActionBar")
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(METRICS.space_3, METRICS.space_2, METRICS.space_3, METRICS.space_2)
    label = QLabel("0 项修改")
    label.setObjectName("changeCount")
    layout.addWidget(label)
    layout.addStretch()
    restore = QPushButton("恢复")
    restore.setObjectName("restoreChanges")
    save = QPushButton("保存")
    save.setObjectName("saveChanges")
    save.setProperty("role", "primary")
    layout.addWidget(restore)
    layout.addWidget(save)
    return bar


def _asset_more_menu(
    parent: QToolButton,
    asset_id: str,
    callback: Callable[[str, str], None],
    theme: ThemeName,
    capabilities: AssetCapabilities,
) -> QMenu:
    menu = QMenu(parent)
    for key, label, enabled, reason in (
        ("replace-clipboard", "从剪贴板替换", capabilities.replace, "该资产不能替换"),
        (
            "open-original",
            "打开原始参考图",
            capabilities.open_original,
            "该资产没有原始参考表示",
        ),
        (
            "set-render",
            "设为首选表示",
            capabilities.set_render,
            "没有多个可选渲染表示",
        ),
        (
            "show-directory",
            "在资源管理器中显示",
            capabilities.show_directory,
            "该资产没有本地目录",
        ),
        ("restore", "恢复上一版本", capabilities.restore, "该资产没有可恢复历史"),
    ):
        action = menu.addAction(icon(key, theme), label)
        action.setEnabled(enabled)
        if not enabled:
            action.setToolTip(reason)
        action.triggered.connect(lambda checked=False, aid=asset_id, name=key: callback(aid, name))
    return menu


def _unmanaged_reference_state(
    item: DesktopAssetItem,
) -> tuple[str, str]:
    if item.kind == "external":
        return "远程图片 · 构建时会产生提示", "statusWarning"
    if item.kind == "local" and item.exists:
        return "普通路径图片 · 尚未转换", "statusWarning"
    if item.diagnostic is not None:
        return item.diagnostic.message, "statusError"
    if item.asset_id is not None:
        return "逻辑资产缺失 · 请检查资源目录", "statusError"
    return "无效或越界的资源引用", "statusError"


def _unmanaged_reference_actions(
    item: DesktopAssetItem,
) -> tuple[tuple[str, str], ...]:
    actions: list[tuple[str, str]] = []
    if item.capabilities.open_reference:
        actions.append(("打开链接" if item.kind == "external" else "查看文件", "open"))
    if item.capabilities.convert:
        actions.append(("转换为逻辑资产", "convert"))
    return tuple(actions)


def _readonly_value() -> QLabel:
    label = QLabel("未记录")
    label.setObjectName("sourceValue")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _first_provenance_value(assets: list[AssetManifest], keys: tuple[str, ...]) -> str:
    for asset in assets:
        found = _find_nested_value(asset.provenance, keys)
        if found:
            return found
        for representation in asset.representations:
            found = _find_nested_value(representation.metadata, keys)
            if found:
                return found
    return ""


def _find_nested_value(value: object, keys: tuple[str, ...]) -> str:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        for key in keys:
            candidate = mapping.get(key)
            if candidate not in (None, "", []):
                return str(candidate)
        for nested in mapping.values():
            found = _find_nested_value(nested, keys)
            if found:
                return found
    elif isinstance(value, list):
        for nested in cast(list[object], value):
            found = _find_nested_value(nested, keys)
            if found:
                return found
    return ""


def _source_method_label(assets: list[AssetManifest]) -> str:
    return _first_provenance_value(assets, ("method", "extraction_method"))


def _question_number(reference: str) -> str:
    match = re.search(
        r"(?:第\s*([0-9]+)\s*题|(?:题|question|q)\s*([0-9]+))",
        reference,
        re.IGNORECASE,
    )
    if match:
        return next(value for value in match.groups() if value is not None)
    return ""


def _history_operation_label(operation: str) -> str:
    labels = {
        "add": "新建题目",
        "upsert": "更新题目",
        "patch": "修改题目",
        "studio_save": "保存题目",
        "tag_register_pending": "登记待整理标签",
        "tag_bulk_edit": "批量修改标签",
        "tag_update": "更新标签定义",
        "asset_ingest": "添加图形资产",
        "asset_edit_begin": "开始编辑图形",
        "asset_edit_saved": "保存图形编辑",
        "asset_render": "重新渲染图形",
        "asset_replace": "替换图形文件",
        "asset_restore": "恢复上一版本",
    }
    return labels.get(operation, operation.replace("_", " "))


def _history_field_label(field: str) -> str:
    return {
        "title": "标题",
        "type": "题型",
        "subject": "学科",
        "chapter": "章节",
        "topics": "标签",
        "difficulty": "难度",
        "status": "状态",
        "language": "语言",
        "source": "来源",
        "stem_md": "题干",
        "options_md": "选项",
        "answer_md": "答案",
        "solution_md": "解析",
        "rubric_md": "评分要点",
        "review_notes_md": "审阅备注",
    }.get(field, field)


def _format_timestamp(value: str) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return value
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = cast(QLayoutItem | None, layout.takeAt(0))
        if item is None:
            break
        widget = cast(QWidget | None, item.widget())
        if widget is not None:
            widget.deleteLater()


def _refresh_widget_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class PreviewWebView(QWebEngineView):
    """Preview surface that preserves the documented image-menu shortcut."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context_menu_shortcut = QShortcut(QKeySequence("Shift+F10"), self)
        self._context_menu_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._context_menu_shortcut.activated.connect(self._open_focused_image_menu)

    def _open_focused_image_menu(self) -> None:
        self.page().runJavaScript(
            "document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', {"
            'key: "F10", shiftKey: true, bubbles: true'
            "}));"
        )


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
        self.preview = PreviewWebView()
        self.preview.setAccessibleName("题目预览")
        self.editor_bridge = EditorBridge()
        self.preview_bridge = PreviewBridge()
        self._wire_channels()
        self._configure_web_settings()
        self._set_page_backgrounds(theme)
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
        self._set_page_backgrounds(theme)
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
            "(() => {"
            "let style=document.getElementById('qbank-theme');"
            "if(!style){"
            "style=document.createElement('style');"
            "style.id='qbank-theme';"
            "document.head.appendChild(style);"
            "}"
            f"style.textContent={css};"
            "})();"
        )

    def _set_page_backgrounds(self, theme: ThemeName) -> None:
        """Keep unpainted web surfaces aligned during live theme changes."""
        background = QColor(palette_for(theme).surface_elevated)
        self.editor.page().setBackgroundColor(background)
        self.preview.page().setBackgroundColor(background)


def _empty_hint() -> QLabel:
    label = QLabel("没有匹配题目。可清除筛选后查看全部题目。")
    label.setObjectName("emptyState")
    label.setWordWrap(True)
    label.setAccessibleName("筛选结果为空")
    label.hide()
    return label
