"""Capture deterministic qbank Studio acceptance screenshots."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast


@dataclass(frozen=True, slots=True)
class CaptureOptions:
    project: Path
    capture: Path
    theme: str
    scale: str
    state: str
    tab: int


def _parse_options() -> CaptureOptions:
    parser = argparse.ArgumentParser(description="capture a qbank Studio UI state")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--scale", choices=("1", "1.25"), default="1")
    parser.add_argument(
        "--state",
        choices=("main", "selection", "manager", "overview", "preferences"),
        default="main",
    )
    parser.add_argument("--tab", type=int, choices=range(4), default=0)
    args = parser.parse_args()
    return CaptureOptions(
        project=args.project,
        capture=args.capture,
        theme=args.theme,
        scale=args.scale,
        state=args.state,
        tab=args.tab,
    )


def main() -> int:
    """Open a real project-backed Studio state and save one PNG."""
    options = _parse_options()
    os.environ["QT_SCALE_FACTOR"] = options.scale
    return _run(options)


def _run(options: CaptureOptions) -> int:
    """Build the real Studio process after Qt scaling has been configured."""

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget

    from qbank.bootstrap import create_project_services
    from qbank.context import ProjectContext
    from qbank.desktop.controller import DesktopController, InteractiveRenderer
    from qbank.desktop.main_window import DesktopMainWindow
    from qbank.presentation.studio.design.palette import ThemeName
    from qbank.presentation.studio.design.stylesheet import apply_theme

    project = options.project.resolve()
    context = ProjectContext.from_root(project)
    services = create_project_services(context)
    application = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
    application.setApplicationName("qbank Studio UI Audit")
    theme = cast(ThemeName, options.theme)
    apply_theme(application, theme)
    controller = DesktopController(
        context,
        services,
        cast(InteractiveRenderer, services.renderer),
    )
    window = DesktopMainWindow(controller, theme)
    window.resize(1680, 1020)
    window.show()
    capture_target: list[QWidget] = [window]

    def configure_state() -> None:
        capture_target[0] = _show_state(
            window,
            controller,
            theme,
            options.state,
            options.tab,
        )

    def capture() -> None:
        options.capture.parent.mkdir(parents=True, exist_ok=True)
        capture_target[0].grab().save(str(options.capture), "PNG")
        if capture_target[0] is not window:
            capture_target[0].close()
        window.close()
        application.quit()

    QTimer.singleShot(1200, configure_state)
    QTimer.singleShot(4800, capture)
    return application.exec()


def _show_state(
    window: object,
    controller: object,
    theme: str,
    state: str,
    tab: int,
):
    """Configure one interaction state and return the widget to capture."""
    from qbank.desktop.preferences_dialog import StudioPreferences, StudioPreferencesDialog
    from qbank.desktop.tag_dialogs import TagManagerDialog, TagOverviewDialog
    from qbank.models import QueryFilters
    from qbank.presentation.studio.design.palette import ThemeName

    if state == "selection":
        for row in range(min(2, window.navigation.questions.count())):
            window.navigation.questions.item(row).setSelected(True)
        return window
    if state == "main":
        window.navigation.filters_toggle.setChecked(True)
        rows = controller.list_tags()
        if rows and window.current_id is not None:
            question = controller.load_question(window.current_id).question
            excluded = next(
                (row.slug for row in rows if row.slug not in question.topics),
                None,
            )
            window.navigation.set_query_state(
                "all",
                QueryFilters(
                    text=question.title[:4],
                    topics=question.topics[:1],
                    excluded_topics=[excluded] if excluded is not None else [],
                    question_type=question.type,
                    status=question.status,
                    difficulty_min=question.difficulty,
                    difficulty_max=question.difficulty,
                    chapter=question.chapter,
                    year=int(question.created_at[:4]) if question.created_at else None,
                    limit=100_000,
                ),
            )
        return window
    if state == "preferences":
        dialog = StudioPreferencesDialog(
            StudioPreferences(theme=cast(ThemeName, theme)),
            cast(ThemeName, theme),
            window,
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return dialog
    dialog_type = TagManagerDialog if state == "manager" else TagOverviewDialog
    dialog = dialog_type(controller, theme, window)
    if isinstance(dialog, TagOverviewDialog):
        dialog.tabs.setCurrentIndex(tab)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


if __name__ == "__main__":
    raise SystemExit(main())
