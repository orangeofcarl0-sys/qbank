"""Single-source Studio design system.

Qt-specific entry points live in :mod:`stylesheet` so non-GUI desktop logic can
render themed HTML without importing the optional PySide6 dependency.
"""

from qbank.presentation.studio.design.palette import ThemeName

__all__ = ["ThemeName"]
