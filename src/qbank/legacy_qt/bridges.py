"""Narrow QWebChannel bridges for the embedded editor and preview."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot


class EditorBridge(QObject):
    """Receive only editor readiness and source-buffer changes."""

    ready = Signal()
    source_edited = Signal(str)

    @Slot()
    def editorReady(self) -> None:
        """Notify Qt that the CodeMirror instance is ready."""
        self.ready.emit()

    @Slot(str)
    def sourceChanged(self, source: str) -> None:
        """Forward one debounced CodeMirror change."""
        self.source_edited.emit(source)


class PreviewBridge(QObject):
    """Receive a closed set of logical-asset UI requests."""

    action_requested = Signal(str, str)
    asset_dropped = Signal(str, str, str)
    context_menu_requested = Signal(str, int, int)

    @Slot(str, str)
    def requestAction(self, asset_id: str, action: str) -> None:
        """Forward a menu action; dispatch validates the closed action name."""
        self.action_requested.emit(asset_id, action)

    @Slot(str, int, int)
    def requestContextMenu(self, asset_id: str, x: int, y: int) -> None:
        """Request a native Qt context menu at preview viewport coordinates."""
        self.context_menu_requested.emit(asset_id, x, y)

    @Slot(str, str, str)
    def assetDropped(self, asset_id: str, name: str, data_uri: str) -> None:
        """Forward a dropped local file as a browser-decoded data URI."""
        self.asset_dropped.emit(asset_id, name, data_uri)
