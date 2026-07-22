"""Central QtAwesome icon registry."""

from __future__ import annotations

from typing import Any, cast

import qtawesome  # type: ignore[import-untyped]  # Upstream has no PEP 561 marker.
from PySide6.QtGui import QIcon

from qbank.presentation.studio.design.palette import ThemeName, palette_for

_NAMES = {
    "save": "fa5s.save",
    "undo": "fa5s.undo",
    "redo": "fa5s.redo",
    "validate": "fa5s.check-circle",
    "source": "fa5s.code",
    "preview": "fa5s.eye",
    "split": "fa5s.columns",
    "properties": "fa5s.sliders-h",
    "settings": "fa5s.cog",
    "theme": "fa5s.adjust",
    "clear": "fa5s.times",
    "copy": "fa5s.copy",
    "open-project": "fa5s.folder-open",
    "import": "fa5s.file-import",
    "delete": "fa5s.trash-alt",
    "paper": "fa5s.file-alt",
    "build": "fa5s.hammer",
    "export": "fa5s.file-export",
    "more": "fa5s.ellipsis-h",
    "add": "fa5s.plus",
    "remove": "fa5s.minus",
    "search": "fa5s.search",
    "edit": "fa5s.edit",
    "replace-file": "fa5s.file-import",
    "replace-clipboard": "fa5s.clipboard",
    "open-original": "fa5s.external-link-alt",
    "render": "fa5s.sync-alt",
    "set-render": "fa5s.star",
    "show-directory": "fa5s.folder-open",
    "restore": "fa5s.history",
    "question": "fa5s.file-alt",
    "warning": "fa5s.exclamation-triangle",
    "chevron-down": "fa5s.chevron-down",
    "chevron-up": "fa5s.chevron-up",
}


def icon(name: str, theme: ThemeName = "light", *, semantic: str | None = None) -> QIcon:
    """Create an icon by stable semantic name through QtAwesome."""
    palette = palette_for(theme)
    color = (
        getattr(palette, semantic, palette.text_secondary) if semantic else palette.text_secondary
    )
    try:
        factory = cast(Any, qtawesome).icon
        return cast(QIcon, factory(_NAMES[name], color=color))
    except KeyError:
        return QIcon()
