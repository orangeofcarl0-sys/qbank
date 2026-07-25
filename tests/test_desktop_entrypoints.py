"""Coverage for the optional desktop composition entry points."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6.QtCore")


def test_desktop_qt_composition_handles_owned_and_existing_applications(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qbank.legacy_qt as desktop_package
    import qbank.legacy_qt.qt as desktop_qt

    root, _config = project
    events: list[object] = []

    class FakeApplication:
        current: FakeApplication | None = None

        def __init__(self, _argv: object = None) -> None:
            type(self).current = self

        @classmethod
        def instance(cls) -> FakeApplication | None:
            return cls.current

        def setApplicationName(self, value: str) -> None:
            events.append(("application", value))

        def setOrganizationName(self, value: str) -> None:
            events.append(("organization", value))

        def exec(self) -> int:
            events.append("exec")
            return 23

    class FakeWindow:
        def __init__(self, controller: object, theme: str) -> None:
            events.append(("window", controller, theme))

        def show(self) -> None:
            events.append("show")

    monkeypatch.setattr(desktop_qt, "QApplication", FakeApplication)
    monkeypatch.setattr(desktop_qt, "DesktopMainWindow", FakeWindow)
    monkeypatch.setattr(desktop_qt, "DesktopController", lambda *args: ("controller", args))
    monkeypatch.setattr(desktop_qt, "apply_theme", lambda app, theme: events.append(theme))
    monkeypatch.setenv("QBANK_STUDIO_THEME", "dark")

    FakeApplication.current = FakeApplication()
    assert desktop_qt.launch_desktop(root) == 0
    FakeApplication.current = None
    assert desktop_qt.launch_desktop(root) == 23
    assert "dark" in events and "show" in events and "exec" in events

    monkeypatch.setattr(desktop_qt, "launch_desktop", lambda project=None: 7)
    assert desktop_package.launch(root) == 7


def test_studio_gallery_entrypoint_captures_and_runs(  # noqa: C901
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qbank.studio_gallery as entrypoint

    events: list[object] = []

    class FakeApplication:
        current: FakeApplication | None = None

        def __init__(self, _argv: object = None) -> None:
            type(self).current = self

        @classmethod
        def instance(cls) -> FakeApplication | None:
            return cls.current

        def setApplicationName(self, value: str) -> None:
            events.append(value)

        def exec(self) -> int:
            events.append("exec")
            return 17

        def quit(self) -> None:
            events.append("quit")

    class FakeGrab:
        def save(self, path: str, format_: str) -> bool:
            events.append((path, format_))
            return True

    class FakeGallery:
        def __init__(self, theme: str) -> None:
            events.append(theme)

        def show(self) -> None:
            events.append("show")

        def grab(self) -> FakeGrab:
            return FakeGrab()

    class FakeTimer:
        @staticmethod
        def singleShot(_delay: int, callback: Callable[[], None]) -> None:
            callback()

    monkeypatch.setattr(entrypoint, "QApplication", FakeApplication)
    monkeypatch.setattr(entrypoint, "StudioGallery", FakeGallery)
    monkeypatch.setattr(entrypoint, "QTimer", FakeTimer)
    monkeypatch.setattr(entrypoint, "apply_theme", lambda app, theme: events.append(theme))
    target = tmp_path / "gallery" / "capture.png"
    monkeypatch.setattr(
        entrypoint.sys,
        "argv",
        ["qbank-studio-gallery", "--theme", "dark", "--capture", str(target)],
    )

    assert entrypoint.main() == 17
    assert target.parent.is_dir()
    assert (str(target), "PNG") in events
    assert "quit" in events

    FakeApplication.current = FakeApplication()
    monkeypatch.setattr(entrypoint.sys, "argv", ["qbank-studio-gallery"])
    assert entrypoint.main() == 17
