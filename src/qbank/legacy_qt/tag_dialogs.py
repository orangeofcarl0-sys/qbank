"""Native Qt dialogs for project-level tag management and lightweight charts."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Literal, cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qbank.errors import QBankError
from qbank.legacy_qt.controller import DesktopController
from qbank.models import (
    QueryFilters,
    TagCoverageCell,
    TagMutationResult,
    TagStatus,
    TagUsage,
    TaxonomyTag,
)
from qbank.presentation.studio.design.palette import ThemeName, palette_for


class TagManagerDialog(QDialog):
    """Dense Zotero-like tag registry editor backed only by application services."""

    changed = Signal()
    theme_name: ThemeName

    def __init__(
        self,
        controller: DesktopController,
        theme: ThemeName,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme_name = theme
        self._rows: list[TagUsage] = []
        self._last_history_token: str | None = None
        self.setWindowTitle("标签管理器")
        self.setMinimumSize(780, 480)
        self.table = self._create_table()
        self._create_buttons()
        self._build_layout()
        self.refresh()

    def _create_table(self) -> QTableWidget:
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["标签", "Slug", "题目数", "别名", "状态", "颜色"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        return table

    def _create_buttons(self) -> None:
        self.rename_button = QPushButton("重命名")
        self.merge_button = QPushButton("合并")
        self.delete_button = QPushButton("删除")
        self.alias_button = QPushButton("设置别名")
        self.color_button = QPushButton("设置颜色")
        self.undo_button = QPushButton("撤销上次操作")
        self.undo_button.setEnabled(False)
        self.rename_button.clicked.connect(self._rename)
        self.merge_button.clicked.connect(self._merge)
        self.delete_button.clicked.connect(self._delete)
        self.alias_button.clicked.connect(self._set_aliases)
        self.color_button.clicked.connect(self._set_color)
        self.undo_button.clicked.connect(self._undo)

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        intro = QLabel("题目 topics 是关系事实；此处只管理规范名称、别名、颜色与状态。")
        intro.setObjectName("fieldHint")
        layout.addWidget(intro)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        for button in (
            self.rename_button,
            self.merge_button,
            self.delete_button,
            self.alias_button,
            self.color_button,
            self.undo_button,
        ):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addWidget(_close_button_box(self))

    def refresh(self) -> None:
        """Reload counts and metadata after every committed operation."""
        self._rows = self.controller.list_tags()
        self.table.setRowCount(len(self._rows))
        for row_index, usage in enumerate(self._rows):
            metadata = usage.metadata
            values = (
                metadata.name_zh if metadata and metadata.name_zh else usage.slug,
                usage.slug,
                str(usage.count),
                "、".join(metadata.aliases) if metadata else "",
                metadata.status.value if metadata else TagStatus.PENDING.value,
                metadata.color if metadata and metadata.color else "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, usage.slug)
                if column == 5 and value:
                    item.setBackground(QColor(value))
                self.table.setItem(row_index, column, item)
        if self._rows and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def _selected(self) -> TagUsage | None:
        row = self.table.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _rename(self) -> None:
        usage = self._selected()
        if usage is None:
            return
        value, accepted = QInputDialog.getText(
            self, "重命名标签", "新的规范 slug：", text=usage.slug
        )
        if accepted and value.strip() and value.strip() != usage.slug:
            self._apply(
                lambda dry_run: self.controller.rename_tag(usage.slug, value, dry_run=dry_run)
            )

    def _merge(self) -> None:
        usage = self._selected()
        if usage is None:
            return
        value, accepted = QInputDialog.getText(self, "合并标签", "合并到规范 slug：")
        if accepted and value.strip():
            self._apply(
                lambda dry_run: self.controller.merge_tag(usage.slug, value, dry_run=dry_run)
            )

    def _delete(self) -> None:
        usage = self._selected()
        if usage is not None:
            self._apply(lambda dry_run: self.controller.delete_tag(usage.slug, dry_run=dry_run))

    def _set_aliases(self) -> None:
        usage = self._selected()
        if usage is None:
            return
        metadata = usage.metadata or TaxonomyTag(slug=usage.slug, status=TagStatus.PENDING)
        initial = ", ".join(metadata.aliases)
        value, accepted = QInputDialog.getText(
            self, "设置标签别名", "别名（逗号分隔）：", text=initial
        )
        if not accepted:
            return
        aliases = [item.strip() for item in value.split(",") if item.strip() != usage.slug]
        updated = metadata.model_copy(update={"aliases": list(dict.fromkeys(aliases))})
        self._apply(lambda dry_run: self.controller.update_tag(updated, dry_run=dry_run))

    def _set_color(self) -> None:
        usage = self._selected()
        if usage is None:
            return
        metadata = usage.metadata or TaxonomyTag(slug=usage.slug, status=TagStatus.PENDING)
        selected = QColorDialog.getColor(QColor(metadata.color or "#527da6"), self, "标签颜色")
        if selected.isValid():
            updated = metadata.model_copy(update={"color": selected.name()})
            self._apply(lambda dry_run: self.controller.update_tag(updated, dry_run=dry_run))

    def _undo(self) -> None:
        if self._last_history_token is None:
            return
        token = self._last_history_token
        self._apply(lambda dry_run: self.controller.undo_tag(token, dry_run=dry_run))

    def _apply(self, operation: Callable[[bool], TagMutationResult]) -> None:
        try:
            planned = operation(True)
            if not self._confirm(planned):
                return
            committed = operation(False)
        except (QBankError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "标签操作失败", str(exc))
            return
        self._last_history_token = committed.history_token
        self.undo_button.setEnabled(self._last_history_token is not None)
        self.refresh()
        self.changed.emit()

    def _confirm(self, result: TagMutationResult) -> bool:
        diffs = "\n".join(
            f"{change.id}: {', '.join(change.before)} → {', '.join(change.after)}"
            for change in result.changes[:10]
        )
        if len(result.changes) > 10:
            diffs += f"\n…另有 {len(result.changes) - 10} 道题"
        if not diffs:
            diffs = "仅修改标签注册表，不改题目 topics。"
        answer = QMessageBox.question(
            self,
            "确认标签变更",
            f"影响 {result.affected_questions} 道题。\n\n{diffs}",
            QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Apply


class TagOverviewDialog(QDialog):
    """Frequency bars, Top-N co-occurrence, and compact coverage heat maps."""

    filter_requested = Signal(object)
    theme_name: ThemeName

    def __init__(
        self,
        controller: DesktopController,
        theme: ThemeName,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.theme_name = theme
        self.data = controller.tag_overview(top_n=10)
        self.setWindowTitle("标签概览")
        self.setMinimumSize(900, 560)
        self.resize(1180, 720)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._frequency_table(), "频次")
        self.tabs.addTab(self._cooccurrence_table(), "共现")
        self.tabs.addTab(self._coverage_table(self.data.year_coverage, "year"), "年份 × 标签")
        self.tabs.addTab(self._coverage_table(self.data.chapter_coverage, "chapter"), "章节 × 标签")
        layout = QVBoxLayout(self)
        hint = QLabel("点击条形、矩阵或热力格，将条件带回主窗口继续筛选。")
        hint.setObjectName("fieldHint")
        layout.addWidget(hint)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(_close_button_box(self))

    def _frequency_table(self) -> QTableWidget:
        table = QTableWidget(len(self.data.frequencies), 2)
        table.setHorizontalHeaderLabels(["标签", "题目数"])
        maximum = max((usage.count for usage in self.data.frequencies), default=1)
        for row, usage in enumerate(self.data.frequencies):
            item = QTableWidgetItem(_tag_label(usage))
            item.setData(Qt.ItemDataRole.UserRole, usage.slug)
            table.setItem(row, 0, item)
            bar = QProgressBar()
            bar.setRange(0, maximum)
            bar.setValue(usage.count)
            bar.setFormat(f"{usage.count}")
            table.setCellWidget(row, 1, bar)
        _finish_chart_table(table)
        table.cellClicked.connect(partial(self._frequency_clicked, table))
        return table

    def _frequency_clicked(self, table: QTableWidget, row: int, column: int) -> None:
        del column
        item = table.item(row, 0)
        if item is not None:
            self.filter_requested.emit(
                QueryFilters(topics=[str(item.data(Qt.ItemDataRole.UserRole))])
            )

    def _cooccurrence_table(self) -> QTableWidget:
        tags = [usage.slug for usage in self.data.frequencies]
        counts = {(item.left, item.right): item.count for item in self.data.cooccurrences}
        frequencies = {usage.slug: usage.count for usage in self.data.frequencies}
        table = QTableWidget(len(tags), len(tags))
        table.setVerticalHeaderLabels([f"{index + 1}  {tag}" for index, tag in enumerate(tags)])
        _set_tag_headers(table, tags, numbered=True)
        maximum = max([*counts.values(), *frequencies.values()], default=1)
        for row, left in enumerate(tags):
            for column, right in enumerate(tags):
                pair = (left, right) if left < right else (right, left)
                count = frequencies[left] if left == right else counts.get(pair, 0)
                item = QTableWidgetItem(str(count) if count else "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, [left] if left == right else [left, right])
                item.setBackground(_heat_color(self.theme_name, count, maximum))
                table.setItem(row, column, item)
        _finish_chart_table(table)
        table.cellClicked.connect(partial(self._matrix_clicked, table))
        return table

    def _matrix_clicked(self, table: QTableWidget, row: int, column: int) -> None:
        item = table.item(row, column)
        if item is not None:
            topics = [
                str(value) for value in cast(list[object], item.data(Qt.ItemDataRole.UserRole))
            ]
            self.filter_requested.emit(QueryFilters(topics=topics, topic_mode="and"))

    def _coverage_table(
        self, cells: list[TagCoverageCell], mode: Literal["year", "chapter"]
    ) -> QTableWidget:
        axes = sorted({cell.axis for cell in cells})
        tags = [usage.slug for usage in self.data.frequencies]
        counts = {(cell.axis, cell.tag): cell.count for cell in cells}
        maximum = max(counts.values(), default=1)
        table = QTableWidget(len(axes), len(tags))
        table.setVerticalHeaderLabels(axes)
        _set_tag_headers(table, tags, numbered=False)
        for row, axis in enumerate(axes):
            for column, tag in enumerate(tags):
                count = counts.get((axis, tag), 0)
                item = QTableWidgetItem(str(count) if count else "")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(_heat_color(self.theme_name, count, maximum))
                table.setItem(row, column, item)
        _finish_chart_table(table)
        table.cellClicked.connect(partial(self._coverage_clicked, table, axes, tags, mode))
        return table

    def _coverage_clicked(
        self,
        table: QTableWidget,
        axes: list[str],
        tags: list[str],
        mode: Literal["year", "chapter"],
        row: int,
        column: int,
    ) -> None:
        item = table.item(row, column)
        if item is None or not item.text():
            return
        values: dict[str, object] = {"topics": [tags[column]]}
        if mode == "year" and axes[row].isdigit():
            values["year"] = int(axes[row])
        elif mode == "chapter" and axes[row] != "未记录":
            values["chapter"] = axes[row]
        self.filter_requested.emit(QueryFilters.model_validate(values))


def _tag_label(usage: TagUsage) -> str:
    if usage.metadata is not None and usage.metadata.name_zh:
        return f"{usage.metadata.name_zh} · {usage.slug}"
    return usage.slug


def _finish_chart_table(table: QTableWidget) -> None:
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)


def _close_button_box(dialog: QDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    button = box.button(QDialogButtonBox.StandardButton.Close)
    button.setText("关闭")
    button.setAccessibleName("关闭窗口")
    box.rejected.connect(dialog.reject)
    return box


def _set_tag_headers(table: QTableWidget, tags: list[str], *, numbered: bool) -> None:
    for column, tag in enumerate(tags):
        label = str(column + 1) if numbered else _compact_tag(tag)
        item = QTableWidgetItem(label)
        item.setToolTip(tag)
        item.setData(Qt.ItemDataRole.UserRole, tag)
        table.setHorizontalHeaderItem(column, item)


def _compact_tag(tag: str) -> str:
    return tag if len(tag) <= 11 else f"{tag[:10]}…"


def _heat_color(theme: ThemeName, count: int, maximum: int) -> QColor:
    base = QColor(palette_for(theme).selection)
    base.setAlpha(30 + round(190 * count / maximum) if count else 0)
    return base


__all__ = ["TagManagerDialog", "TagOverviewDialog"]
