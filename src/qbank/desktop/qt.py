"""PySide6 composition entry for the lightweight desktop editor."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QApplication

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.desktop.controller import DesktopController, InteractiveRenderer
from qbank.desktop.main_window import DesktopMainWindow
from qbank.desktop.preferences_dialog import load_studio_preferences
from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.stylesheet import apply_theme


def launch_desktop(project: Path | None = None) -> int:
    """Create one project context and run the Qt event loop."""
    context = (
        ProjectContext.from_root(project) if project is not None else ProjectContext.discover()
    )
    services = create_project_services(context)
    application = QApplication.instance()
    owns_application = application is None
    if application is None:
        application = QApplication(sys.argv)
    application = cast(QApplication, application)
    application.setApplicationName("qbank")
    application.setOrganizationName("qbank")
    environment_theme = os.environ.get("QBANK_STUDIO_THEME")
    theme: ThemeName = (
        cast(ThemeName, environment_theme)
        if environment_theme in {"light", "dark"}
        else load_studio_preferences().theme
    )
    apply_theme(application, theme)
    controller = DesktopController(
        context,
        services,
        cast(InteractiveRenderer, services.renderer),
    )
    window = DesktopMainWindow(controller, theme)
    window.show()
    if not owns_application:
        return 0
    return application.exec()
