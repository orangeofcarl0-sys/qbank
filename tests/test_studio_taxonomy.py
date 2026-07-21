"""Studio tag facets, canonical topic editor, manager, and chart interactions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QToolButton,
)
from pytestqt.qtbot import QtBot

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.desktop.controller import DesktopController
from qbank.desktop.tag_dialogs import TagManagerDialog, TagOverviewDialog
from qbank.desktop.widgets import NavigationPane, TopicTagEditor
from qbank.models import QueryFilters, TagStatus
from qbank.operations import add_question_in_context
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

    waves = next(
        pane.tags.list.item(index)
        for index in range(pane.tags.list.count())
        if pane.tags.list.item(index).data(Qt.ItemDataRole.UserRole) == "waves"
    )
    pane.tags.list.itemClicked.emit(waves)
    assert pane.current_filters().topics == ["waves"]
    assert {
        row.id
        for row in controller.navigation_result(view="all", filters=pane.current_filters()).rows
    } == {"OPT-TAG-0001", "OPT-TAG-0002"}

    interference = next(
        pane.tags.list.item(index)
        for index in range(pane.tags.list.count())
        if pane.tags.list.item(index).data(Qt.ItemDataRole.UserRole) == "interference"
    )
    pane.tags.list.itemClicked.emit(interference)
    assert pane.current_filters().topics == ["interference", "waves"]
    assert controller.navigation_result(view="all", filters=pane.current_filters()).total == 1
    pane.tags.mode.setCurrentIndex(1)
    assert pane.current_filters().topic_mode == "or"
    assert controller.navigation_result(view="all", filters=pane.current_filters()).total == 2

    waves = next(
        pane.tags.list.item(index)
        for index in range(pane.tags.list.count())
        if pane.tags.list.item(index).data(Qt.ItemDataRole.UserRole) == "waves"
    )
    pane.tags.list.itemClicked.emit(waves)
    assert pane.current_filters().excluded_topics == ["waves"]
    assert controller.navigation_result(view="all", filters=pane.current_filters()).total == 0
    assert any(
        "排除：waves" in button.text() for button in pane.filter_chips.findChildren(QToolButton)
    )

    pane.clear_filters()
    pane.facets.status.setCurrentIndex(pane.facets.status.findData("draft"))
    filtered = controller.navigation_result(view="all", filters=pane.current_filters())
    assert [row.id for row in filtered.rows] == ["OPT-TAG-0002"]


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
