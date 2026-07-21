"""Capture deterministic qbank Studio and component-gallery review states."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path
from typing import Any


def main() -> int:
    """Launch one real Qt state and capture its full native window rectangle."""
    args = _arguments()
    _configure_environment(args.scale)
    application, window = _create_window(args)
    _schedule_capture(application, window, args)
    return application.exec()


def _configure_environment(scale: str) -> None:
    """Set process-wide Qt options before importing PySide6."""
    os.environ["QT_SCALE_FACTOR"] = scale
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")


def _create_window(args: argparse.Namespace) -> tuple[Any, Any]:
    from PySide6.QtWidgets import QApplication

    from qbank.presentation.studio.design.stylesheet import apply_theme

    application = QApplication(sys.argv)
    application.setApplicationName("qbank UI audit")
    apply_theme(application, args.theme)
    if args.target == "gallery":
        from qbank.presentation.studio.gallery import StudioGallery

        window: Any = StudioGallery(args.theme)
    else:
        if args.project is None:
            raise SystemExit("--project is required for Studio captures")
        window = _studio_window(args.project, args.theme)
    scale = float(args.scale)
    window.resize(round(1480 / scale), round(900 / scale))
    window.show()
    window.raise_()
    window.activateWindow()
    return application, window


def _schedule_capture(application: Any, window: Any, args: argparse.Namespace) -> None:
    from PySide6.QtCore import QTimer

    def prepare_state() -> None:
        _prepare_state(window, args.target, args.state)

    def capture() -> None:
        _capture_window(application, window, args)

    prepare_delay = 1800 if args.target == "gallery" else 1200
    capture_delay = 4200 if args.target == "gallery" else 2600
    QTimer.singleShot(prepare_delay, prepare_state)
    QTimer.singleShot(capture_delay, capture)


def _capture_window(application: Any, window: Any, args: argparse.Namespace) -> None:
    """Compose the active transient surface and save one deterministic frame."""
    window.raise_()
    window.activateWindow()
    overlay = _activate_overlay(window, args.target, args.state)
    application.processEvents()
    pixmap = window.grab()
    _paint_overlay(window, pixmap, overlay)
    pixmap = _scale_pixmap(pixmap, window, _capture_scale(args.scale, window))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(args.output), "PNG"):
        raise RuntimeError(f"could not save screenshot: {args.output}")
    application.quit()


def _activate_overlay(window: Any, target: str, state: str) -> Any | None:
    if target != "studio":
        return None
    if state == "image-menu":
        _open_image_menu(window)
        return getattr(window, "_asset_menu", None)
    if state == "validation":
        dialog = getattr(window, "_audit_dialog", None)
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
        return dialog
    return None


def _paint_overlay(window: Any, pixmap: Any, overlay: Any | None) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter

    if overlay is None or not overlay.isVisible():
        return
    position = window.mapFromGlobal(overlay.mapToGlobal(QPoint(0, 0)))
    painter = QPainter(pixmap)
    painter.drawPixmap(position, overlay.grab())
    painter.end()


def _scale_pixmap(pixmap: Any, window: Any, capture_scale: float) -> Any:
    from PySide6.QtCore import Qt

    target_width = round(window.width() * capture_scale)
    target_height = round(window.height() * capture_scale)
    if pixmap.width() == target_width and pixmap.height() == target_height:
        return pixmap
    return pixmap.scaled(
        target_width,
        target_height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _capture_scale(requested_scale: str, window: Any) -> float:
    """Return deterministic physical pixels per logical audit pixel."""
    if sys.platform == "win32":
        system_dpi = int(ctypes.windll.user32.GetDpiForSystem())
        return (system_dpi / 96.0) * float(requested_scale)
    return float(window.screen().devicePixelRatio())


def _prepare_state(window: Any, target: str, state: str) -> None:
    if target != "studio":
        return
    if state == "image-menu":
        _open_image_menu(window)
    elif state == "metadata":
        window.drawer.show()
        window.drawer.raise_()
    elif state == "loading":
        question_id = window.current_id or "OPT-INT-0001"
        window._preview_loading = True
        window.workspace.show_loading(question_id)
    elif state == "validation":
        _open_validation(window)
    elif state == "preview-bottom":
        window.workspace.preview.page().runJavaScript(
            "window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'});"
        )


def _open_validation(window: Any) -> None:
    from PySide6.QtWidgets import QMessageBox

    dialog = QMessageBox(window)
    dialog.setWindowTitle("校验未通过")
    dialog.setText("choice_answer：选择题答案必须对应已有选项")
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    dialog.setAccessibleName("题目校验结果")
    window._audit_dialog = dialog
    dialog.open()
    dialog.raise_()
    dialog.activateWindow()


def _open_image_menu(window: Any) -> None:
    if window.current_id is None:
        return
    document = window.controller.load_question(window.current_id)
    asset_id = document.assets[0].asset_id if document.assets else "diagram"
    window.workspace.set_asset_actions_enabled(True)
    window._show_asset_context_menu(asset_id, 360, 300)


def _studio_window(project: Path, theme: str) -> Any:
    from typing import cast

    from qbank.bootstrap import create_project_services
    from qbank.context import ProjectContext
    from qbank.desktop.controller import DesktopController, InteractiveRenderer
    from qbank.desktop.main_window import DesktopMainWindow
    from qbank.presentation.studio.design.palette import ThemeName

    context = ProjectContext.from_root(project)
    services = create_project_services(context)
    controller = DesktopController(
        context,
        services,
        cast(InteractiveRenderer, services.renderer),
    )
    return DesktopMainWindow(controller, cast(ThemeName, theme))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("studio", "gallery"), default="studio")
    parser.add_argument("--project", type=Path)
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument(
        "--state",
        choices=(
            "main",
            "image-menu",
            "metadata",
            "loading",
            "validation",
            "preview-bottom",
        ),
        default="main",
    )
    parser.add_argument("--scale", choices=("1", "1.25"), default="1")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
