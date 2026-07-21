"""Modern native-behavior controls for the Studio inspector."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QSpinBox, QToolButton

from qbank.presentation.studio.design.icons import icon
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.tokens import tokens_for


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
