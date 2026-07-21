"""Generated Qt stylesheet and application theme entry point."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QProxyStyle

from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.tokens import tokens_for


class StudioProxyStyle(QProxyStyle):
    """Small native-style adapter; geometry remains platform-owned."""


def build_stylesheet(theme: ThemeName) -> str:
    """Generate the complete Qt Widgets stylesheet from semantic tokens."""
    t = tokens_for(theme)
    p, m = t.palette, t.metrics
    return f"""
    QWidget {{ color: {p.text_primary}; font-family: "{t.typography.qt_family}"; font-size: {t.typography.ui_size}px; }}
    QMainWindow, QDialog {{ background: {p.background}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p.background}; border: 0; }}
    QDockWidget {{ color: {p.text_primary}; titlebar-close-icon: none; titlebar-normal-icon: none; }}
    QDockWidget::title {{ padding: {m.space_2}px {m.space_3}px; background: {p.surface}; border-bottom: {m.border_width}px solid {p.border_subtle}; }}
    #navigationPane, #detailDrawer QWidget {{ background: {p.surface}; }}
    QToolBar {{ min-height: {m.toolbar_height}px; spacing: {m.space_1}px; padding: 0 {m.space_2}px; background: {p.surface}; border: 0; border-bottom: {m.border_width}px solid {p.border_subtle}; }}
    QToolButton {{ min-width: {m.control_height}px; min-height: {m.control_height}px; border: {m.border_width}px solid transparent; border-radius: {m.radius_small}px; padding: 0 {m.space_1}px; }}
    QToolButton:hover {{ background: {p.surface_hover}; }}
    QToolButton:focus {{ border-color: {p.focus}; }}
    QToolButton:checked {{ color: {p.accent}; background: {p.selection}; border-color: {p.border_strong}; }}
    QToolButton:disabled {{ color: {p.text_disabled}; }}
    QToolButton#spinStepButton {{ min-width: 0; min-height: 0; padding: 0; border: 0; border-radius: {m.radius_small}px; background: transparent; }}
    QToolButton#spinStepButton:hover {{ background: {p.surface_hover}; }}
    QToolButton#spinStepButton:pressed {{ background: {p.selection}; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ min-height: {m.control_height}px; background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_strong}; border-radius: {m.radius_medium}px; padding: 0 {m.space_2}px; selection-background-color: {p.selection}; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {p.focus}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus, QListWidget:focus {{ border: {m.border_width}px solid {p.focus}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {p.text_disabled}; background: {p.surface}; }}
    QComboBox {{ padding-right: {m.space_8}px; }}
    QComboBox QAbstractItemView {{ color: {p.text_primary}; background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_strong}; outline: 0; selection-background-color: {p.selection}; selection-color: {p.text_primary}; padding: {m.space_1}px; }}
    QSpinBox {{ padding-right: {m.space_8}px; }}
    QListWidget {{ background: transparent; border: 0; outline: 0; alternate-background-color: {p.background}; }}
    QListWidget::item {{ padding: {m.space_2}px; border-radius: {m.radius_small}px; }}
    QListWidget::item:hover {{ background: {p.surface_hover}; }}
    QListWidget::item:selected {{ color: {p.text_primary}; background: {p.selection}; }}
    QListWidget::item:disabled {{ color: {p.text_disabled}; }}
    QTabWidget::pane {{ border: 0; border-top: {m.border_width}px solid {p.border_subtle}; }}
    QTabBar::tab {{ padding: {m.space_2}px {m.space_3}px; color: {p.text_secondary}; border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {p.text_primary}; border-bottom-color: {p.accent}; }}
    QSplitter::handle {{ background: {p.border_subtle}; width: {m.border_width}px; }}
    QStatusBar {{ color: {p.text_secondary}; background: {p.surface}; border-top: {m.border_width}px solid {p.border_subtle}; }}
    QMenu {{ background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_strong}; padding: {m.space_1}px; }}
    QMenu::item {{ padding: {m.space_2}px {m.space_6}px {m.space_2}px {m.space_3}px; border-radius: {m.radius_small}px; }}
    QMenu::item:selected {{ color: {p.text_primary}; background: {p.selection}; }}
    QMessageBox {{ background: {p.surface_elevated}; }}
    QLabel#sectionLabel, QLabel#activeFilter {{ color: {p.text_secondary}; }}
    #metadataPanel QLabel#fieldLabel {{ color: {p.text_secondary}; font-size: {t.typography.small_size}px; font-weight: 500; }}
    QLabel#emptyState {{ color: {p.text_secondary}; padding: {m.space_3}px {m.space_2}px; }}
    QLabel#statusSuccess {{ color: {p.success}; }}
    QLabel#statusWarning {{ color: {p.warning}; }}
    QLabel#statusError {{ color: {p.error}; }}
    QLabel#documentTitle {{ font-size: {t.typography.title_size}px; font-weight: 600; }}
    QFrame[frameShape="6"] {{ background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_medium}px; }}
    """


def apply_theme(application: QApplication, theme: ThemeName) -> None:
    """Apply one Studio theme without changing the native window frame."""
    if not isinstance(application.style(), StudioProxyStyle):
        application.setStyle(StudioProxyStyle(application.style()))
    application.setProperty("qbankTheme", theme)
    application.setStyleSheet(build_stylesheet(theme))
