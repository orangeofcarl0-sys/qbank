"""PySide6 composition entry for the lightweight desktop editor."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QApplication

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.desktop.controller import DesktopController, InteractiveRenderer
from qbank.desktop.main_window import DesktopMainWindow


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
    application.setApplicationName("qbank")
    application.setOrganizationName("qbank")
    controller = DesktopController(
        context,
        services,
        cast(InteractiveRenderer, services.renderer),
    )
    window = DesktopMainWindow(controller)
    window.show()
    if not owns_application:
        return 0
    return application.exec()
