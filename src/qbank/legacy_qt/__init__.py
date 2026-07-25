"""Lazy entry points for the retained QBank Studio Legacy adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def launch(project: Path | None = None) -> int:
    """Launch the retained QBank Studio Legacy desktop application."""
    from qbank.legacy_qt.qt import launch_desktop

    return launch_desktop(project)


__all__ = ["launch"]
