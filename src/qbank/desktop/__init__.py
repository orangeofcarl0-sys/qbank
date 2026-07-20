"""Lazy entry points for the optional lightweight desktop editor."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def launch(project: Path | None = None) -> int:
    """Launch the optional PySide6 desktop application."""
    from qbank.desktop.qt import launch_desktop

    return launch_desktop(project)


__all__ = ["launch"]
