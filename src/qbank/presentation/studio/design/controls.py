"""Modern native-behavior controls for the Studio inspector."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QLayout,
    QLayoutItem,
    QSpinBox,
    QToolButton,
    QWidget,
)

from qbank.presentation.studio.design.icons import icon
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.tokens import tokens_for


class FlowLayout(QLayout):
    """Compact wrapping layout for narrow, keyboard-accessible chip bars."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        horizontal_spacing: int = METRICS.space_1,
        vertical_spacing: int = METRICS.space_1,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._horizontal_spacing = horizontal_spacing
        self._vertical_spacing = vertical_spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return cast(QLayoutItem, None)

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout_items(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._layout_items(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )

    def _layout_items(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(
            margins.left(),
            margins.top(),
            -margins.right(),
            -margins.bottom(),
        )
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._horizontal_spacing
            if line_height and next_x - self._horizontal_spacing > area.right() + 1:
                x = area.x()
                y += line_height + self._vertical_spacing
                next_x = x + hint.width() + self._horizontal_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class ModernComboBox(QComboBox):
    """Combo box with a single rounded surface and embedded semantic chevron."""

    theme_name: ThemeName

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self._popup_open = False
        self.setObjectName("modernComboBox")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def set_theme(self, theme: ThemeName) -> None:
        """Refresh theme-dependent painting without rebuilding the control."""
        self.theme_name = theme
        self.update()

    def showPopup(self) -> None:
        self._popup_open = True
        self.update()
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._popup_open = False
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        tokens = tokens_for(self.theme_name)
        palette, metrics = tokens.palette, tokens.metrics
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        surface = palette.surface_elevated if self.isEnabled() else palette.surface
        border = palette.focus if self.hasFocus() else palette.border_strong
        if self.underMouse() and self.isEnabled() and not self.hasFocus():
            border = palette.focus
        painter.setBrush(QColor(surface))
        painter.setPen(QPen(QColor(border), metrics.border_width))
        painter.drawRoundedRect(rect, metrics.radius_medium, metrics.radius_medium)

        text_color = palette.text_primary if self.isEnabled() else palette.text_disabled
        painter.setPen(QColor(text_color))
        text_rect = rect.adjusted(metrics.space_3, 0, -metrics.space_8, 0)
        display = painter.fontMetrics().elidedText(
            self.currentText(),
            Qt.TextElideMode.ElideRight,
            text_rect.width(),
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            display,
        )

        arrow_rect = QRect(
            rect.right() - metrics.space_6,
            rect.center().y() - metrics.icon_small // 2,
            metrics.icon_small,
            metrics.icon_small,
        )
        arrow_name = "chevron-up" if self._popup_open else "chevron-down"
        icon(arrow_name, self.theme_name).paint(painter, arrow_rect)


class ModernSpinBox(QSpinBox):
    """Spin box with keyboard/wheel behavior and borderless icon steppers."""

    theme_name: ThemeName

    def __init__(self, theme: ThemeName = "light") -> None:
        super().__init__()
        self.theme_name = theme
        self.setObjectName("modernSpinBox")
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._increase = self._step_button("增加数值", self.stepUp)
        self._decrease = self._step_button("减少数值", self.stepDown)
        self.set_theme(theme)

    def set_theme(self, theme: ThemeName) -> None:
        """Update embedded stepper icons for the active semantic palette."""
        self.theme_name = theme
        self._increase.setIcon(icon("chevron-up", theme))
        self._decrease.setIcon(icon("chevron-down", theme))
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        margin = 2
        width = METRICS.space_6
        available = max(2, self.height() - margin * 2)
        upper_height = available // 2
        left = self.width() - width - margin
        self._increase.setGeometry(left, margin, width, upper_height)
        self._decrease.setGeometry(
            left,
            margin + upper_height,
            width,
            available - upper_height,
        )

    def _step_button(
        self,
        accessible_name: str,
        callback: Callable[[], None],
    ) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("spinStepButton")
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setIconSize(QSize(METRICS.icon_small, METRICS.icon_small))
        button.clicked.connect(lambda _checked=False: callback())
        return button
