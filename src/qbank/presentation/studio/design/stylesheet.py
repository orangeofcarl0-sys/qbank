"""Generated Qt stylesheet and application theme entry point."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QProxyStyle

from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.tokens import tokens_for


class StudioProxyStyle(QProxyStyle):
    """Small native-style adapter; geometry remains platform-owned."""


def _point_size(pixel_size: int) -> float:
    """Convert a 96-DPI design pixel size to a valid scalable Qt point size."""
    return pixel_size * 72.0 / 96.0


def _point_css(pixel_size: int) -> str:
    return f"{_point_size(pixel_size):g}pt"


def build_stylesheet(theme: ThemeName) -> str:
    """Generate the complete Qt Widgets stylesheet from semantic tokens."""
    t = tokens_for(theme)
    p, m = t.palette, t.metrics
    return f"""
    QWidget {{ color: {p.text_primary}; }}
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
    QTableWidget {{ color: {p.text_primary}; background: {p.surface_elevated}; alternate-background-color: {p.background}; border: {m.border_width}px solid {p.border_subtle}; gridline-color: {p.border_subtle}; selection-background-color: {p.selection}; selection-color: {p.text_primary}; }}
    QTableWidget::item:hover {{ background: {p.surface_hover}; }}
    QTableWidget::item:selected {{ color: {p.text_primary}; background: {p.selection}; }}
    QHeaderView::section {{ color: {p.text_primary}; background: {p.surface}; border: 0; border-right: {m.border_width}px solid {p.border_subtle}; border-bottom: {m.border_width}px solid {p.border_strong}; padding: {m.space_1}px {m.space_2}px; font-weight: 600; }}
    QProgressBar {{ color: {p.text_primary}; background: {p.background}; border: 0; border-radius: {m.radius_small}px; text-align: right; }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: {m.radius_small}px; }}
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
    #navigationPane QLineEdit, #navigationPane QComboBox {{ min-height: 28px; max-height: 28px; border-radius: {m.radius_small}px; }}
    QFrame#facetFilterPanel {{ background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_medium}px; }}
    QFrame#tagSelector {{ background: transparent; border-top: {m.border_width}px solid {p.border_subtle}; }}
    QToolButton#tagSelectorToggle {{ color: {p.text_primary}; font-weight: 600; text-align: left; }}
    QListWidget#tagFacetList {{ background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_small}px; }}
    QListWidget#tagFacetList::item {{ min-height: 20px; padding: 2px {m.space_2}px; }}
    QToolButton#filterChip {{ min-height: 22px; max-height: 22px; color: {p.accent}; background: {p.selection}; border: {m.border_width}px solid {p.border_subtle}; border-radius: 11px; padding: 0 {m.space_2}px; }}
    QToolButton#filterChip:hover {{ border-color: {p.focus}; }}
    #detailDrawer {{ background: {p.surface}; }}
    #detailDrawer QScrollArea, #detailDrawer QScrollArea > QWidget > QWidget {{ background: {p.surface}; }}
    #detailDrawer QLineEdit, #detailDrawer QComboBox, #detailDrawer QSpinBox {{ min-height: 28px; max-height: 28px; border-radius: {m.radius_small}px; }}
    #metadataPanel QLabel#fieldLabel, QLabel#fieldLabel {{ color: {p.text_secondary}; font-size: {_point_css(t.typography.small_size)}; font-weight: 500; }}
    QLabel#inspectorSectionLabel {{ color: {p.text_primary}; font-weight: 600; padding-top: {m.space_2}px; border-bottom: {m.border_width}px solid {p.border_subtle}; }}
    QLabel#inspectorTitle {{ color: {p.text_primary}; font-size: {_point_css(16)}; font-weight: 600; }}
    QLabel#inspectorId {{ color: {p.text_secondary}; font-family: {t.typography.mono_family}; }}
    QLabel#summaryBadge {{ color: {p.text_secondary}; background: {p.background}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_small}px; padding: 2px {m.space_2}px; }}
    QLabel#summaryBadge[state="success"] {{ color: {p.success}; border-color: {p.success}; }}
    QLabel#summaryBadge[state="error"] {{ color: {p.error}; border-color: {p.error}; }}
    QLabel#summaryWarning {{ color: {p.warning}; background: {p.background}; border-left: 2px solid {p.warning}; padding: {m.space_1}px {m.space_2}px; }}
    QLabel#fieldHint {{ color: {p.text_secondary}; font-size: {_point_css(t.typography.small_size)}; }}
    QLabel#sourceValue {{ color: {p.text_primary}; background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_small}px; padding: {m.space_2}px; }}
    QLabel#sourceValue[missing="true"] {{ color: {p.text_disabled}; }}
    QLabel#assetName, QLabel#timelineTitle, QLabel#emptyStateTitle {{ color: {p.text_primary}; font-weight: 600; }}
    QLabel#assetThumbnail {{ background: {p.background}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_small}px; }}
    QLabel#timelineBullet {{ color: {p.accent}; padding-top: 2px; }}
    QWidget#timelineRow {{ border-bottom: {m.border_width}px solid {p.border_subtle}; }}
    QFrame#assetCard {{ background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_medium}px; }}
    QFrame#inspectorEmptyState {{ background: transparent; border: {m.border_width}px dashed {p.border_strong}; border-radius: {m.radius_medium}px; }}
    QFrame#inspectorActionBar {{ background: {p.surface_elevated}; border-top: {m.border_width}px solid {p.border_strong}; }}
    QPushButton {{ min-height: 28px; padding: 0 {m.space_3}px; background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_strong}; border-radius: {m.radius_small}px; }}
    QPushButton:hover {{ border-color: {p.focus}; background: {p.surface_hover}; }}
    QPushButton:focus {{ border-color: {p.focus}; }}
    QPushButton#saveChanges {{ color: {p.background}; background: {p.accent}; border-color: {p.accent}; font-weight: 600; }}
    QPushButton#saveChanges:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
    QPushButton#compactButton {{ min-height: 26px; padding: 0 {m.space_2}px; font-size: {_point_css(t.typography.small_size)}; }}
    QToolButton#compactIconButton {{ min-width: 26px; min-height: 26px; max-width: 26px; max-height: 26px; }}
    QToolButton#compactIconButton::menu-indicator {{ image: none; }}
    QToolButton#topicTag {{ min-height: 24px; padding: 0 {m.space_2}px; color: {p.accent}; background: {p.selection}; border: {m.border_width}px solid {p.border_subtle}; border-radius: 12px; }}
    QToolButton#representationToggle {{ min-height: 24px; padding: 0; color: {p.text_secondary}; text-align: left; }}
    QLabel#emptyState {{ color: {p.text_secondary}; padding: {m.space_3}px {m.space_2}px; }}
    QLabel#statusSuccess {{ color: {p.success}; }}
    QLabel#statusWarning {{ color: {p.warning}; }}
    QLabel#statusError {{ color: {p.error}; }}
    QLabel#documentTitle {{ font-size: {_point_css(t.typography.title_size)}; font-weight: 600; }}
    QFrame[frameShape="6"] {{ background: {p.surface_elevated}; border: {m.border_width}px solid {p.border_subtle}; border-radius: {m.radius_medium}px; }}
    """


def apply_theme(application: QApplication, theme: ThemeName) -> None:
    """Apply one Studio theme without changing the native window frame."""
    if not isinstance(application.style(), StudioProxyStyle):
        application.setStyle(StudioProxyStyle(application.style()))
    typography = tokens_for(theme).typography
    application_font = application.font()
    application_font.setFamily(typography.qt_family)
    application_font.setPointSizeF(_point_size(typography.ui_size))
    application.setFont(application_font)
    application.setProperty("qbankTheme", theme)
    application.setStyleSheet(build_stylesheet(theme))
