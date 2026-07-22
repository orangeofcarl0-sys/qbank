"""Studio tag facets, canonical topic editor, manager, and chart interactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("PySide6.QtCore")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QToolButton,
)
from pytestqt.qtbot import QtBot

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.desktop.controller import DesktopController
from qbank.desktop.tag_dialogs import TagManagerDialog, TagOverviewDialog
from qbank.desktop.widgets import NavigationPane, TopicTagEditor
from qbank.models import (
    DesktopQuestionSummary,
    QueryFilters,
    QuestionStatus,
    QuestionType,
    TagStatus,
)
from qbank.operations import add_question_in_context
from qbank.presentation.studio.design.controls import FlowLayout
from qbank.rendering import RenderService


def _controller(
    project: tuple[Path, Any],
    make_question: Any,
) -> DesktopController:
    root, _ = project
    context = ProjectContext.from_root(root)
    services = create_project_services(context)
    for question in (
        make_question(
            id="OPT-TAG-0001",
            title="Michelson 干涉",
            topics=["interference", "waves"],
            chapter="interferometry",
        ),
        make_question(
            id="OPT-TAG-0002",
            title="Fraunhofer 衍射",
            topics=["diffraction", "waves"],
            chapter="diffraction",
            status="draft",
        ),
    ):
        add_question_in_context(context, question, services=services.mutations)
    services.tags.normalize(dry_run=False, command="test normalize")
    interference = services.tags.show_tag("interference").metadata
    assert interference is not None
    services.tags.update_tag(
        interference.model_copy(
            update={
                "name_zh": "干涉",
                "name_en": "Interference",
                "aliases": ["相干叠加"],
                "color": "#527da6",
                "status": TagStatus.ACTIVE,
            }
        ),
        dry_run=False,
        command="test metadata",
    )
    return DesktopController(context, create_project_services(context), RenderService(context))


def _tag_action(pane: NavigationPane, slug: str, action: str) -> QToolButton:
    item = next(
        pane.tags.list.item(index)
        for index in range(pane.tags.list.count())
        if pane.tags.list.item(index).data(Qt.ItemDataRole.UserRole) == slug
    )
    widget = pane.tags.list.itemWidget(item)
    assert widget is not None
    prefix = {"include": "包含", "exclude": "排除", "clear": "清除"}[action]
    return next(
        button
        for button in widget.findChildren(QToolButton)
        if button.accessibleName().startswith(prefix)
    )


def test_navigation_tag_states_and_field_facets_form_one_query(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    pane = NavigationPane()
    qtbot.addWidget(pane)
    pane.set_navigation_data(controller.navigation_data())
    result = controller.navigation_result(view="all", filters=pane.current_filters())
    pane.set_rows(result.rows, None)
    pane.set_tag_rows(result.tags, result.total)

    assert pane.tags.list.item(0).data(Qt.ItemDataRole.UserRole) == "waves"
    pane.tags.sort.setCurrentIndex(1)
    assert [
        pane.tags.list.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(pane.tags.list.count())
    ] == ["diffraction", "interference", "waves"]
    pane.tags.search.setText("干涉")
    assert pane.tags.list.count() == 1
    assert pane.tags.list.item(0).data(Qt.ItemDataRole.UserRole) == "interference"
    pane.tags.search.clear()
    pane.tags.sort.setCurrentIndex(0)

    _tag_action(pane, "waves", "include").click()
    assert pane.current_filters().topics == ["waves"]
    assert {
        row.id
        for row in controller.navigation_result(view="all", filters=pane.current_filters()).rows
    } == {"OPT-TAG-0001", "OPT-TAG-0002"}

    _tag_action(pane, "interference", "include").click()
    assert pane.current_filters().topics == ["interference", "waves"]
    assert controller.navigation_result(view="all", filters=pane.current_filters()).total == 1
    pane.tags.mode.setCurrentIndex(1)
    assert pane.current_filters().topic_mode == "or"
    assert controller.navigation_result(view="all", filters=pane.current_filters()).total == 2

    _tag_action(pane, "waves", "exclude").click()
    assert pane.current_filters().excluded_topics == ["waves"]
    assert controller.navigation_result(view="all", filters=pane.current_filters()).total == 0
    assert any(
        "排除：waves" in button.text() for button in pane.filter_chips.findChildren(QToolButton)
    )

    pane.clear_filters()
    pane.facets.status.setCurrentIndex(pane.facets.status.findData("draft"))
    filtered = controller.navigation_result(view="all", filters=pane.current_filters())
    assert [row.id for row in filtered.rows] == ["OPT-TAG-0002"]


def test_clear_tag_filter_refreshes_the_complete_result_once(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    pane = NavigationPane()
    qtbot.addWidget(pane)
    pane.set_navigation_data(controller.navigation_data())
    initial = controller.navigation_result(view="all", filters=pane.current_filters())
    pane.set_rows(initial.rows, None)
    pane.set_tag_rows(initial.tags, initial.total)
    totals: list[int] = []

    def refresh() -> None:
        result = controller.navigation_result(
            view=pane.current_view(), filters=pane.current_filters()
        )
        pane.set_rows(result.rows, None)
        pane.set_tag_rows(result.tags, result.total)
        totals.append(result.total)

    pane.filters_changed.connect(refresh)
    _tag_action(pane, "interference", "include").click()
    assert totals == [1]
    totals.clear()

    pane.clear_filter.click()

    assert totals == [2]
    assert pane.current_view() == "all"
    assert pane.current_filters().topics == []
    assert pane.questions.count() == 2
    assert pane.tags.list.count() == 3
    assert not pane.clear_filter.isEnabled()


def test_saved_view_is_an_editable_visible_snapshot(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    saved = QueryFilters(topics=["interference"], limit=100_000)
    controller.save_view("interference-view", saved, dry_run=False)
    pane = NavigationPane()
    qtbot.addWidget(pane)
    pane.set_navigation_data(controller.navigation_data())
    view_events: list[str] = []
    search_events: list[str] = []
    pane.view_changed.connect(view_events.append)
    pane.search_changed.connect(search_events.append)
    pane.select_view("interference-view")

    assert view_events == ["interference-view"]
    assert search_events == []
    assert pane.current_filters().topics == ["interference"]
    assert (
        controller.navigation_result(view="interference-view", filters=pane.current_filters()).total
        == 1
    )
    pane._remove_chip("topic", "interference")

    assert pane.current_filters().topics == []
    assert pane.current_view_is_modified()
    assert "已修改" in pane.active_filter.text()
    assert (
        controller.navigation_result(view="interference-view", filters=pane.current_filters()).total
        == 2
    )
    assert controller.navigation_result(view="interference-view", filters=None).total == 1

    pane.restore_current_view()

    assert pane.current_filters().topics == ["interference"]
    assert not pane.current_view_is_modified()
    assert "已修改" not in pane.active_filter.text()
    filter_events: list[bool] = []
    pane.filters_changed.connect(lambda: filter_events.append(True))

    pane.clear_filters()

    assert filter_events == [True]
    assert pane.current_view() == "all"
    assert pane.current_filters().topics == []


def test_special_view_membership_combines_with_complete_visible_filters(
    project: tuple[Path, Any], make_question: Any
) -> None:
    controller = _controller(project, make_question)
    controller.current_paper_ids = ("OPT-TAG-0001",)

    assert (
        controller.navigation_result(
            view="current_paper",
            filters=QueryFilters(topics=["waves"], limit=100_000),
        ).total
        == 1
    )
    assert (
        controller.navigation_result(
            view="current_paper",
            filters=QueryFilters(topics=["diffraction"], limit=100_000),
        ).total
        == 0
    )


def test_filter_chips_wrap_and_tag_controls_expose_accessible_states(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    pane = NavigationPane()
    qtbot.addWidget(pane)
    data = controller.navigation_data()
    pane.set_navigation_data(data)
    result = controller.navigation_result(view="all", filters=pane.current_filters())
    pane.set_rows(result.rows, "NOT-IN-RESULT")
    pane.set_tag_rows(result.tags, result.total)
    pane.resize(256, 900)
    pane.show()
    pane.set_transient_filters(
        QueryFilters(
            text="optics",
            topics=["interference"],
            excluded_topics=["diffraction"],
            status=QuestionStatus(data.statuses[0]),
            question_type=QuestionType(data.question_types[0]),
            chapter=data.chapters[0],
            year=data.years[0] if data.years else None,
            difficulty_min=1,
            difficulty_max=4,
            limit=100_000,
        )
    )
    qtbot.wait(50)

    layout = cast(FlowLayout, pane.filter_chips.layout())
    buttons = pane.filter_chips.findChildren(QToolButton)
    assert len(buttons) >= 8
    assert layout.heightForWidth(pane.filter_chips.width()) > 22
    assert len({button.y() for button in buttons}) > 1
    assert all(
        button.geometry().right() <= pane.filter_chips.contentsRect().right() for button in buttons
    )
    assert pane.tags.sort.accessibleName() == "标签排序方式"
    assert pane.tags.mode.accessibleName() == "多标签匹配方式"
    assert "当前题目不在筛选结果中" in pane.active_filter.text()
    pane.set_current_question(result.rows[0].id)
    assert "当前题目不在筛选结果中" not in pane.active_filter.text()
    tag_item = pane.tags.list.item(0)
    assert "标签" in str(tag_item.data(Qt.ItemDataRole.AccessibleTextRole))
    assert "单击或按空格循环" in str(tag_item.data(Qt.ItemDataRole.AccessibleDescriptionRole))


def test_tag_rows_cycle_with_space_and_advanced_filters_preserve_navigation_height(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    pane = NavigationPane()
    qtbot.addWidget(pane)
    pane.resize(256, 900)
    pane.show()
    pane.set_navigation_data(controller.navigation_data())
    result = controller.navigation_result(view="all", filters=pane.current_filters())
    pane.set_rows(result.rows, result.rows[0].id)
    pane.set_tag_rows(result.tags, result.total)
    pane.advanced_toggle.setChecked(True)
    qtbot.wait(50)

    assert pane.advanced_scroll.isVisible()
    assert pane.questions.height() >= pane.questions.minimumHeight()
    assert pane.questions.minimumHeight() > 100

    item = next(
        pane.tags.list.item(index)
        for index in range(pane.tags.list.count())
        if pane.tags.list.item(index).data(Qt.ItemDataRole.UserRole) == "interference"
    )
    pane.tags.list.itemClicked.emit(item)
    assert pane.current_filters().topics == ["interference"]
    qtbot.keyClick(pane.tags.list, Qt.Key.Key_Space)
    assert pane.current_filters().topics == []
    assert pane.current_filters().excluded_topics == ["interference"]
    qtbot.keyClick(pane.tags.list, Qt.Key.Key_Space)
    assert pane.current_filters().excluded_topics == []


def test_saved_facets_restore_complete_values_and_empty_draft_view(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    pane = NavigationPane()
    qtbot.addWidget(pane)
    pane.set_navigation_data(controller.navigation_data())
    filters = QueryFilters(
        subject="astronomy",
        language="fr-FR",
        status=QuestionStatus.DEPRECATED,
        question_type=QuestionType.ESSAY,
        limit=100_000,
    )

    pane.set_query_state("all", filters)

    assert pane.current_filters().semantic_values() == filters.semantic_values()
    assert pane.facets.subject.text() == "astronomy"
    assert pane.facets.language.text() == "fr-FR"
    assert pane.facets.status.currentData() == "deprecated"
    assert pane.facets.question_type.currentData() == "essay"

    pane.set_query_state(
        "draft",
        QueryFilters(status=QuestionStatus.DRAFT, subject="astronomy", limit=100_000),
    )
    empty = controller.navigation_result(view="draft", filters=pane.current_filters())
    pane.set_rows(empty.rows, None)
    pane.set_tag_rows(empty.tags, empty.total)
    assert pane.current_view() == "draft"
    assert pane.current_filters().status == QuestionStatus.DRAFT


def test_open_question_is_not_an_implicit_bulk_selection(qtbot: QtBot) -> None:
    pane = NavigationPane()
    qtbot.addWidget(pane)
    rows = [
        DesktopQuestionSummary(
            id="Q-001",
            title="Question one",
            subject="optics",
            status="reviewed",
            question_type="other",
            difficulty=1,
            needs_redraw=False,
        ),
        DesktopQuestionSummary(
            id="Q-002",
            title="Question two",
            subject="optics",
            status="reviewed",
            question_type="other",
            difficulty=1,
            needs_redraw=False,
        ),
    ]

    pane.set_rows(rows, "Q-001")

    assert pane.questions.currentItem().data(Qt.ItemDataRole.UserRole) == "Q-001"
    assert pane.selected_question_ids() == []
    assert not pane.bulk_add.isEnabled()
    assert not pane.bulk_remove.isEnabled()
    assert pane.selection_summary.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    for button in (pane.bulk_add, pane.bulk_remove):
        assert button.minimumWidth() == button.maximumWidth() == 68
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        assert not button.icon().isNull()
        assert button.text() == "标签"


def test_topic_editor_resolves_aliases_blocks_duplicates_and_marks_pending(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    editor = TopicTagEditor()
    qtbot.addWidget(editor)
    editor.set_registry(controller.list_tags())
    pending: list[str] = []
    editor.pending_topic_created.connect(pending.append)

    editor.input.setText("相干叠加")
    editor.input.returnPressed.emit()
    assert editor.topics() == ["interference"]
    editor.input.setText("Interference")
    editor.input.returnPressed.emit()
    assert editor.topics() == ["interference"]

    editor.input.setText("New Concept")
    editor.input.returnPressed.emit()
    assert editor.topics() == ["interference", "new-concept"]
    assert pending == ["new-concept"]
    assert any(
        "new-concept · 待整理" in tag.text() for tag in editor.tags.findChildren(QToolButton)
    )


def test_tag_manager_and_overview_emit_real_query_filters(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    manager = TagManagerDialog(controller, "light")
    qtbot.addWidget(manager)
    assert manager.table.rowCount() == 3
    assert {manager.table.item(row, 1).text() for row in range(manager.table.rowCount())} == {
        "diffraction",
        "interference",
        "waves",
    }
    assert "关闭" in {button.text() for button in manager.findChildren(QPushButton)}

    overview = TagOverviewDialog(controller, "light")
    qtbot.addWidget(overview)
    emitted: list[QueryFilters] = []
    overview.filter_requested.connect(lambda value: emitted.append(cast(QueryFilters, value)))
    frequency = cast(QTableWidget, overview.tabs.widget(0))
    overview._frequency_clicked(frequency, 0, 0)
    assert emitted[-1].topics
    pane = NavigationPane()
    qtbot.addWidget(pane)
    pane.set_navigation_data(controller.navigation_data())
    pane.set_transient_filters(emitted[-1])
    result = controller.navigation_result(view="all", filters=pane.current_filters())
    assert result.total >= 1


def test_tag_manager_undo_restores_topics(project: tuple[Path, Any], make_question: Any) -> None:
    controller = _controller(project, make_question)
    changed = controller.rename_tag("waves", "wave-physics", dry_run=False)
    assert changed.history_token is not None
    controller.undo_tag(changed.history_token, dry_run=False)
    assert controller.services.questions.get_question("OPT-TAG-0001").topics == [
        "interference",
        "waves",
    ]


def test_tag_manager_native_actions_preview_commit_and_undo(
    project: tuple[Path, Any],
    make_question: Any,
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _controller(project, make_question)
    manager = TagManagerDialog(controller, "dark")
    qtbot.addWidget(manager)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Apply,
    )

    def select(slug: str) -> None:
        for row in range(manager.table.rowCount()):
            if manager.table.item(row, 1).text() == slug:
                manager.table.selectRow(row)
                return
        raise AssertionError(f"missing tag row: {slug}")

    select("interference")
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("optical-interference", True),
    )
    manager._rename()
    select("diffraction")
    manager._merge()
    select("waves")
    manager._delete()

    select("optical-interference")
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        lambda *_args, **_kwargs: ("光学, fringe", True),
    )
    manager._set_aliases()
    monkeypatch.setattr(
        QColorDialog,
        "getColor",
        lambda *_args, **_kwargs: QColor("#446688"),
    )
    manager._set_color()
    assert manager.undo_button.isEnabled()
    manager._undo()
    assert controller.list_tags()[0].slug == "optical-interference"


def test_overview_matrix_and_heatmap_clicks_emit_combined_filters(
    project: tuple[Path, Any], make_question: Any, qtbot: QtBot
) -> None:
    controller = _controller(project, make_question)
    overview = TagOverviewDialog(controller, "dark")
    qtbot.addWidget(overview)
    emitted: list[QueryFilters] = []
    overview.filter_requested.connect(lambda value: emitted.append(cast(QueryFilters, value)))

    matrix = cast(QTableWidget, overview.tabs.widget(1))
    assert matrix.horizontalHeaderItem(0).text() == "1"
    assert matrix.horizontalHeaderItem(0).toolTip()
    overview._matrix_clicked(matrix, 0, 1)
    assert len(emitted[-1].topics) == 2
    assert emitted[-1].topic_mode == "and"

    years = cast(QTableWidget, overview.tabs.widget(2))
    year_cell = next(
        (row, column)
        for row in range(years.rowCount())
        for column in range(years.columnCount())
        if years.item(row, column).text()
    )
    overview._coverage_clicked(
        years,
        [years.verticalHeaderItem(row).text() for row in range(years.rowCount())],
        [
            str(years.horizontalHeaderItem(column).data(Qt.ItemDataRole.UserRole))
            for column in range(years.columnCount())
        ],
        "year",
        *year_cell,
    )
    assert emitted[-1].year is not None

    chapters = cast(QTableWidget, overview.tabs.widget(3))
    chapter_cell = next(
        (row, column)
        for row in range(chapters.rowCount())
        for column in range(chapters.columnCount())
        if chapters.item(row, column).text()
    )
    overview._coverage_clicked(
        chapters,
        [chapters.verticalHeaderItem(row).text() for row in range(chapters.rowCount())],
        [
            str(chapters.horizontalHeaderItem(column).data(Qt.ItemDataRole.UserRole))
            for column in range(chapters.columnCount())
        ],
        "chapter",
        *chapter_cell,
    )
    assert emitted[-1].chapter in {"diffraction", "interferometry"}
