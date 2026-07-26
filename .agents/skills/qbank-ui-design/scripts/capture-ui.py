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
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from qbank.presentation.studio.design.stylesheet import apply_theme

    application = QApplication(sys.argv)
    application.setApplicationName("qbank UI audit")
    application.setOrganizationName("qbank UI audit")
    QSettings().setValue("studio/detailDrawerWidth", 340)
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
    if hasattr(window, "dirty"):
        window.dirty = False
    application.quit()


def _activate_overlay(window: Any, target: str, state: str) -> Any | None:
    if target != "studio":
        return None
    if state == "image-menu":
        _open_image_menu(window)
        return getattr(window, "_asset_menu", None)
    if state in {"validation", "dirty-confirm", "asset-error"}:
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
    if state.startswith("inspector-") or state == "metadata":
        _prepare_inspector_state(window, state)
        return
    if state == "image-menu":
        _open_image_menu(window)
    elif state == "loading":
        question_id = window.current_id or "OPT-INT-0001"
        window._preview_loading = True
        window.workspace.show_loading(question_id)
    elif state == "validation":
        _open_validation(window)
    elif state == "dirty-confirm":
        _open_dirty_confirmation(window)
    elif state == "asset-error":
        _open_asset_error(window)
    elif state == "preview-bottom":
        window.workspace.preview.page().runJavaScript(
            "window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'});"
        )
    elif state == "theme-switch":
        window.set_theme("dark" if window.theme_name == "light" else "light")


def _prepare_inspector_state(window: Any, state: str) -> None:
    window.drawer.show()
    window.drawer.raise_()
    if state == "inspector-empty-assets":
        _select_question_without_assets(window)
    elif state == "inspector-legacy-assets":
        _select_question_with_legacy_asset(window)
    elif state == "inspector-asset-states":
        _prepare_asset_state_samples(window)
    tab = {
        "metadata": 0,
        "inspector-dirty": 0,
        "inspector-assets": 1,
        "inspector-empty-assets": 1,
        "inspector-legacy-assets": 1,
        "inspector-asset-states": 1,
        "inspector-source": 2,
        "inspector-history": 3,
    }[state]
    window.drawer.tabs.setCurrentIndex(tab)
    if state == "inspector-dirty":
        title = window.drawer.metadata.title
        title.setText(title.text() + "（修订）")
        window._metadata_changed()


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


def _open_dirty_confirmation(window: Any) -> None:
    from PySide6.QtWidgets import QMessageBox

    dialog = QMessageBox(window)
    dialog.setWindowTitle("先保存题目")
    dialog.setText("当前题目有未保存修改。可先保存、放弃修改或取消资产操作。")
    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setStandardButtons(
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel
    )
    dialog.setDefaultButton(QMessageBox.StandardButton.Save)
    dialog.setAccessibleName("未保存资产操作确认")
    window._audit_dialog = dialog
    dialog.open()


def _open_asset_error(window: Any) -> None:
    from PySide6.QtWidgets import QMessageBox

    dialog = QMessageBox(window)
    dialog.setWindowTitle("资产操作失败")
    dialog.setText("题目提交失败；新资产已撤销。\n回滚提示：历史清理失败，原始错误已保留。")
    dialog.setIcon(QMessageBox.Icon.Critical)
    dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    dialog.setAccessibleName("资产事务失败")
    window._audit_dialog = dialog
    dialog.open()


def _open_image_menu(window: Any) -> None:
    if window.current_id is None:
        return
    document = window.controller.load_question(window.current_id)
    asset_id = document.assets[0].asset_id if document.assets else "diagram"
    window.workspace.set_asset_actions_enabled(True)
    window._show_asset_context_menu(asset_id, 360, 300)


def _select_question_without_assets(window: Any) -> None:
    for row in window.controller.list_questions():
        document = window.controller.load_question(row.id)
        if not document.assets and not document.question.assets:
            window._load_question(row.id)
            return


def _select_question_with_legacy_asset(window: Any) -> None:
    for row in window.controller.list_questions():
        document = window.controller.load_question(row.id)
        if not document.assets and document.question.assets:
            window._load_question(row.id)
            return


def _prepare_asset_state_samples(window: Any) -> None:
    from qbank.models import (
        AssetCapabilities,
        AssetManifest,
        DesktopAssetItem,
        Diagnostic,
        DiagnosticCode,
    )

    document = window.controller.load_question(window.current_id)
    logical = next((item for item in document.asset_items if item.kind == "logical"), None)
    if logical is None:
        for row in window.controller.list_questions():
            candidate = window.controller.load_question(row.id)
            logical = next(
                (item for item in candidate.asset_items if item.kind == "logical"),
                None,
            )
            if logical is not None:
                document = candidate
                window._load_question(row.id)
                break
    if logical is None:
        manifest = AssetManifest.model_validate(
            {
                "schema_version": "1.0",
                "asset_id": "reference-only",
                "question_id": document.question.id,
                "role": "reference",
                "status": "final",
                "representations": [
                    {
                        "representation_id": "original-pdf",
                        "format": "pdf",
                        "path": "original.pdf",
                        "purpose": "original-reference",
                        "content_hash": "0" * 64,
                    }
                ],
            }
        )
        logical = DesktopAssetItem(
            kind="logical",
            reference="qbank-asset:reference-only",
            display_name="reference-only",
            asset_id="reference-only",
            manifest=manifest,
            exists=True,
        )
    items = [logical.model_copy(update={"capabilities": AssetCapabilities()})]
    items.extend(
        [
            DesktopAssetItem(
                kind="external",
                reference="HTTPS://example.com/reference.png",
                display_name="外部参考图",
                exists=True,
                diagnostic=Diagnostic(
                    severity="warning",
                    code=DiagnosticCode.EXTERNAL_ASSET,
                    message="外部资源不会自动下载",
                ),
                capabilities=AssetCapabilities(open_reference=True, convert=True),
            ),
            DesktopAssetItem(
                kind="invalid",
                reference="../outside.png",
                display_name="越界资源",
                diagnostic=Diagnostic(
                    code=DiagnosticCode.ASSET_OUTSIDE_ASSETS,
                    message="资源位于 assets 目录之外",
                ),
            ),
        ]
    )
    window.drawer.load_document(document.model_copy(update={"asset_items": items}))


def _studio_window(project: Path, theme: str) -> Any:
    from typing import cast

    from qbank.desktop.controller import DesktopController, InteractiveRenderer
    from qbank.desktop.main_window import DesktopMainWindow

    from qbank.bootstrap import create_project_services
    from qbank.context import ProjectContext
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
            "inspector-assets",
            "inspector-empty-assets",
            "inspector-legacy-assets",
            "inspector-asset-states",
            "inspector-source",
            "inspector-history",
            "inspector-dirty",
            "loading",
            "validation",
            "dirty-confirm",
            "asset-error",
            "preview-bottom",
            "theme-switch",
        ),
        default="main",
    )
    parser.add_argument("--scale", choices=("1", "1.25"), default="1")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
