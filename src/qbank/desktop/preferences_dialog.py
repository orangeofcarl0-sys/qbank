"""Compact Studio preferences dialog and persistent presentation settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from qbank.presentation.studio.design.controls import ModernComboBox
from qbank.presentation.studio.design.metrics import METRICS
from qbank.presentation.studio.design.palette import ThemeName

PreferenceWorkspaceMode = Literal["source", "preview", "split"]

_THEME_KEY = "studio/theme"
_WORKSPACE_KEY = "studio/defaultWorkspaceMode"
_DETAILS_KEY = "studio/showDetailDrawer"
_PROJECT_PATH_KEY = "studio/showProjectPath"


@dataclass(frozen=True, slots=True)
class StudioPreferences:
    """Small, presentation-only set of Studio preferences."""

    theme: ThemeName = "light"
    workspace_mode: PreferenceWorkspaceMode = "split"
    show_detail_drawer: bool = True
    show_project_path: bool = False


def load_studio_preferences(default_theme: ThemeName = "light") -> StudioPreferences:
    """Load validated presentation preferences from the native settings store."""
    settings = _settings()
    theme_value = str(settings.value(_THEME_KEY, default_theme))
    mode_value = str(settings.value(_WORKSPACE_KEY, "split"))
    theme: ThemeName = cast(
        ThemeName, theme_value if theme_value in {"light", "dark"} else default_theme
    )
    workspace_mode: PreferenceWorkspaceMode = cast(
        PreferenceWorkspaceMode,
        mode_value if mode_value in {"source", "preview", "split"} else "split",
    )
    return StudioPreferences(
        theme=theme,
        workspace_mode=workspace_mode,
        show_detail_drawer=_setting_bool(settings.value(_DETAILS_KEY, True), True),
        show_project_path=_setting_bool(settings.value(_PROJECT_PATH_KEY, False), False),
    )


def save_studio_preferences(preferences: StudioPreferences) -> None:
    """Persist Studio presentation preferences without touching qbank data."""
    settings = _settings()
    settings.setValue(_THEME_KEY, preferences.theme)
    settings.setValue(_WORKSPACE_KEY, preferences.workspace_mode)
    settings.setValue(_DETAILS_KEY, preferences.show_detail_drawer)
    settings.setValue(_PROJECT_PATH_KEY, preferences.show_project_path)
    settings.sync()


class StudioPreferencesForm(QWidget):
    """Gallery-friendly preferences primitive used by the native dialog."""

    changed = Signal()

    def __init__(
        self,
        preferences: StudioPreferences,
        theme: ThemeName = "light",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.theme_name = theme
        self.theme = ModernComboBox(theme)
        self.theme.setAccessibleName("界面主题")
        self.theme.addItem("浅色", "light")
        self.theme.addItem("深色", "dark")
        self.workspace_mode = ModernComboBox(theme)
        self.workspace_mode.setAccessibleName("默认编辑视图")
        self.workspace_mode.addItem("源码", "source")
        self.workspace_mode.addItem("预览", "preview")
        self.workspace_mode.addItem("分栏", "split")
        self.show_detail_drawer = QCheckBox("启动时显示题目详情")
        self.show_detail_drawer.setAccessibleName("启动时显示题目详情")
        self.show_project_path = QCheckBox("在顶栏显示完整题库路径")
        self.show_project_path.setAccessibleName("在顶栏显示完整题库路径")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(METRICS.space_3)
        form = QFormLayout()
        form.setHorizontalSpacing(METRICS.space_3)
        form.setVerticalSpacing(METRICS.space_2)
        form.addRow("界面主题", self.theme)
        form.addRow("默认编辑视图", self.workspace_mode)
        layout.addLayout(form)
        layout.addWidget(self.show_detail_drawer)
        layout.addWidget(self.show_project_path)
        hint = QLabel("这些设置只影响 Studio 界面，不会修改题库内容。")
        hint.setObjectName("fieldHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._set_combo_value(self.theme, preferences.theme)
        self._set_combo_value(self.workspace_mode, preferences.workspace_mode)
        self.show_detail_drawer.setChecked(preferences.show_detail_drawer)
        self.show_project_path.setChecked(preferences.show_project_path)
        self.theme.currentIndexChanged.connect(self._emit_changed)
        self.workspace_mode.currentIndexChanged.connect(self._emit_changed)
        self.show_detail_drawer.toggled.connect(self._emit_changed)
        self.show_project_path.toggled.connect(self._emit_changed)

    def _emit_changed(self, *_args: object) -> None:
        """Normalize value-carrying Qt signals to the form's zero-argument signal."""
        self.changed.emit()

    @staticmethod
    def _set_combo_value(combo: ModernComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(index, 0))

    def preferences(self) -> StudioPreferences:
        """Return the fully visible preference state."""
        return StudioPreferences(
            theme=cast(ThemeName, str(self.theme.currentData())),
            workspace_mode=cast(PreferenceWorkspaceMode, str(self.workspace_mode.currentData())),
            show_detail_drawer=self.show_detail_drawer.isChecked(),
            show_project_path=self.show_project_path.isChecked(),
        )

    def set_theme(self, theme: ThemeName) -> None:
        """Keep custom combo icons and popup colors aligned with Studio."""
        self.theme_name = theme
        self.theme.set_theme(theme)
        self.workspace_mode.set_theme(theme)


class StudioPreferencesDialog(QDialog):
    """Native modal window for secondary Studio presentation settings."""

    def __init__(
        self,
        preferences: StudioPreferences,
        theme: ThemeName = "light",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Studio 设置")
        self.setAccessibleName("Studio 设置")
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.space_4,
            METRICS.space_4,
            METRICS.space_4,
            METRICS.space_4,
        )
        layout.setSpacing(METRICS.space_3)
        title = QLabel("界面与工作区")
        title.setObjectName("documentTitle")
        layout.addWidget(title)
        self.form = StudioPreferencesForm(preferences, theme, self)
        layout.addWidget(self.form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        accept = buttons.button(QDialogButtonBox.StandardButton.Ok)
        accept.setText("应用")
        accept.setDefault(True)
        accept.setAccessibleName("应用 Studio 设置")
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("取消")
        cancel.setAccessibleName("取消 Studio 设置")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @classmethod
    def get_preferences(
        cls,
        current: StudioPreferences,
        parent: QWidget | None = None,
    ) -> StudioPreferences | None:
        """Open the modal preferences window and return accepted values."""
        dialog = cls(current, current.theme, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.form.preferences()


def _setting_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _settings() -> QSettings:
    return QSettings("qbank", "qbank")
