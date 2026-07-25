"""Focused behavior checks for Studio widget edge states and helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6.QtCore")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QLineEdit, QListWidgetItem, QWidget
from pytestqt.qtbot import QtBot

from qbank.legacy_qt.widgets import (
    DetailDrawer,
    FacetFilterPanel,
    FriendlyValueEdit,
    NavigationPane,
    TagFacetList,
    TagSelector,
    TopicTagEditor,
    _find_nested_value,
    _first_provenance_value,
    _format_timestamp,
    _line_edit,
    _parse_timestamp,
    _question_number,
    _source_method_label,
    _unmanaged_reference_actions,
    _unmanaged_reference_state,
)
from qbank.models import (
    AssetCapabilities,
    AssetFormat,
    AssetManifest,
    AssetRepresentation,
    DesktopAssetItem,
    DesktopNavigationData,
    DesktopQuestionSummary,
    QueryFilters,
    SavedView,
    TagUsage,
    TaxonomyTag,
)


def _navigation_data() -> DesktopNavigationData:
    return DesktopNavigationData(
        views=[
            SavedView(name="all", protected=True),
            SavedView(name="custom", filters=QueryFilters(subject="optics")),
        ],
        tags=[
            TagUsage(
                slug="interference",
                count=2,
                registered=True,
                metadata=TaxonomyTag(
                    slug="interference",
                    name_zh="干涉",
                    aliases=["wave-interference"],
                ),
            )
        ],
        statuses=["draft"],
        question_types=["calculation"],
        subjects=["optics"],
        chapters=["interferometry"],
        languages=["zh-CN"],
        years=[2025],
    )


def test_facet_tag_selector_and_keyboard_edge_states(qtbot: QtBot) -> None:
    facets = FacetFilterPanel("light")
    selector = TagSelector("light")
    qtbot.addWidget(facets)
    qtbot.addWidget(selector)
    data = _navigation_data()
    facets.set_data(data)
    filters = QueryFilters(
        status="draft",
        question_type="calculation",
        subject="optics",
        chapter="not-in-bank",
        language="zh-CN",
        year=2025,
        difficulty_min=2,
        difficulty_max=4,
        topics=["missing"],
        excluded_topics=["excluded"],
        topic_mode="or",
    )
    facets.set_filters(filters)
    selector.set_filters(filters.topics, filters.excluded_topics, filters.topic_mode)
    selector.set_rows([])
    assert {selector.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(2)} == {
        "missing",
        "excluded",
    }
    assert facets.filters("text", selector).chapter == "not-in-bank"
    selector.search.setText("missing")
    selector.sort.setCurrentIndex(1)
    selector._current_slug = "missing"
    selector._refresh()
    selector._toggle_body(True)
    selector._toggle_body(False)
    selector.clear()
    facets.clear()
    facets.set_theme("dark")

    tag_list = TagFacetList()
    qtbot.addWidget(tag_list)
    key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    tag_list.keyPressEvent(key)
    item = QListWidgetItem("tag")
    item.setData(Qt.ItemDataRole.UserRole, "tag")
    tag_list.addItem(item)
    tag_list.setCurrentItem(item)
    seen: list[str] = []
    tag_list.cycle_requested.connect(seen.append)
    tag_list.keyPressEvent(key)
    assert seen == ["tag"]


def test_navigation_snapshot_chip_and_selection_branches(
    qtbot: QtBot,
) -> None:
    navigation = NavigationPane("light")
    qtbot.addWidget(navigation)
    navigation.set_navigation_data(_navigation_data())
    navigation.select_view("missing")
    with pytest.raises(ValueError, match="saved view not found"):
        navigation.set_query_state("missing", QueryFilters())

    navigation.set_query_state("custom", QueryFilters(subject="electronics"))
    assert navigation.current_view_is_modified()
    navigation.restore_current_view()
    assert not navigation.current_view_is_modified()
    navigation.set_search_loading(True)
    navigation.set_search_loading(False)
    navigation._toggle_facets(True)
    navigation._toggle_facets(False)
    navigation._toggle_advanced(True)
    navigation._toggle_advanced(False)

    filters = QueryFilters(
        text="needle",
        topics=["interference"],
        excluded_topics=["excluded"],
        status="draft",
        question_type="calculation",
        subject="optics",
        chapter="interferometry",
        language="zh-CN",
        year=2025,
        difficulty_min=1,
        difficulty_max=5,
    )
    navigation.set_query_state("all", filters)
    for key, value in (
        ("text", "needle"),
        ("topic", "interference"),
        ("excluded_topic", "excluded"),
        ("status", "draft"),
        ("subject", "optics"),
        ("difficulty_min", "1"),
    ):
        navigation._remove_chip(key, value)

    rows = [
        DesktopQuestionSummary(
            id=f"Q-{index}",
            title=f"Question {index}",
            subject="optics",
            question_type="calculation",
            difficulty=2,
            status="draft",
            needs_redraw=index == 0,
        )
        for index in range(3)
    ]
    navigation.set_rows(rows, None)
    navigation.questions.selectAll()
    navigation._selection_changed()
    assert "等 3 道题" in navigation.selection_summary.text()
    navigation.set_rows([], "missing")
    navigation._emit_question(None, None)

    navigation.set_query_state("custom", QueryFilters(subject="optics"))
    navigation.restore_current_view()


def test_topic_editor_drawer_and_provenance_helpers(  # noqa: PLR0915
    qtbot: QtBot,
) -> None:
    editor = TopicTagEditor()
    qtbot.addWidget(editor)
    editor.set_registry(_navigation_data().tags)
    editor.input.setText("干涉")
    editor._accept_input()
    editor.input.setText("***")
    editor._accept_input()
    editor._completion_activated("missing")
    editor._completion_activated("interference")
    assert editor.topics() == ["interference"]
    editor._remove_topic("interference")

    value = FriendlyValueEdit({"draft": "草稿"})
    qtbot.addWidget(value)
    value.set_raw_value("draft")
    value.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))
    value.setText("reviewed")
    value.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert value.raw_value() == "reviewed"

    drawer = DetailDrawer("light")
    qtbot.addWidget(drawer)
    settings = QSettings()
    settings.setValue("studio/detailDrawerWidth", "invalid")
    assert drawer.preferred_width() == 340
    drawer.set_dirty_state(2, preview_pending=True, needs_redraw=True)
    drawer.set_dirty_state(0, preview_pending=False, needs_redraw=False)

    external = DesktopAssetItem(
        kind="external",
        reference="https://example.com/a.png",
        display_name="a.png",
        capabilities=AssetCapabilities(open_reference=True, convert=True),
    )
    local = DesktopAssetItem(
        kind="local",
        reference="assets/a.png",
        display_name="a.png",
        exists=True,
        capabilities=AssetCapabilities(open_reference=True),
    )
    missing = DesktopAssetItem(
        kind="logical",
        reference="asset:missing",
        display_name="missing",
        asset_id="missing",
    )
    assert _unmanaged_reference_state(external)[1] == "statusWarning"
    assert _unmanaged_reference_state(local)[0].startswith("普通路径")
    assert _unmanaged_reference_state(missing)[0].startswith("逻辑资产缺失")
    assert len(_unmanaged_reference_actions(external)) == 2

    manifest = AssetManifest(
        schema_version="1.0",
        question_id="OPT-INT-0001",
        asset_id="a",
        role="figure",
        status="raw",
        provenance={"nested": [{"method": "ocr"}, {"question_number": 7}]},
        representations=[
            AssetRepresentation(
                representation_id="remote",
                format=AssetFormat.PNG,
                url="https://example.com/a.png",
                purpose="render",
            )
        ],
    )
    assert _find_nested_value({"outer": [{"key": "value"}]}, ("key",)) == "value"
    assert _first_provenance_value([manifest], ("question_number",)) == "7"
    assert _source_method_label([manifest]) == "ocr"
    assert _question_number("第 12 题") == "12"
    assert _question_number("Question 9") == "9"
    assert _question_number("unknown") == ""
    assert _parse_timestamp("invalid") is None
    assert _parse_timestamp("2025-01-01T00:00:00") is None
    assert _parse_timestamp("2025-01-01T00:00:00Z") == datetime(2025, 1, 1, tzinfo=UTC)
    assert _format_timestamp("invalid") == "invalid"
    assert _line_edit(QLineEdit()) is not None
    with pytest.raises(TypeError):
        _line_edit(QWidget())
