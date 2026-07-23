"""Ipe discovery and safe launcher branch coverage without starting applications."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import qbank.infrastructure.ipe as ipe
from qbank.context import ProjectContext
from qbank.errors import AssetCommandError, IpeUnavailableError
from qbank.models import AssetFormat


def test_safe_launcher_execute_paths_are_delegated(
    project: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    launcher = ipe.SafeAssetLauncher(context)
    opened: list[Path] = []
    spawned: list[tuple[str, ...]] = []
    monkeypatch.setattr(ipe, "_system_open", opened.append)
    monkeypatch.setattr(ipe, "_spawn", lambda command, _cwd: spawned.append(command))
    monkeypatch.setattr(
        ipe.IpeToolchain,
        "discover",
        lambda _context: ipe.IpeToolchain(
            ipe=tmp_path / "ipe.exe",
            iperender=tmp_path / "iperender.exe",
            ipetoipe=tmp_path / "ipetoipe.exe",
        ),
    )
    source = tmp_path / "source.ipe"
    launcher.open_file(source, execute=True)
    launcher.open_directory(tmp_path, execute=True)
    launcher.edit_file(source, AssetFormat.IPE, execute=True)
    assert opened == [source, tmp_path]
    assert spawned[0][0].endswith("ipe.exe")

    monkeypatch.setattr(ipe.webbrowser, "open", lambda _url: False)
    with pytest.raises(AssetCommandError, match="browser rejected"):
        launcher.open_url("https://example.com", execute=True)


def test_ipe_executable_resolution_covers_configured_path_directory_and_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configured = tmp_path / "iperender.exe"
    configured.write_bytes(b"exe")
    assert ipe._resolve_executable("iperender.exe", str(configured), ()) == configured.resolve()
    with pytest.raises(IpeUnavailableError, match=r"must be ipetoipe\.exe"):
        ipe._resolve_executable("ipetoipe.exe", str(configured), ())

    directory = tmp_path / "bin"
    directory.mkdir()
    in_directory = directory / "ipetoipe.exe"
    in_directory.write_bytes(b"exe")
    assert ipe._resolve_executable("ipetoipe.exe", None, (directory,)) == in_directory.resolve()

    alternative = tmp_path / "ipe"
    alternative.write_bytes(b"exe")
    monkeypatch.setattr(
        ipe.shutil, "which", lambda name: str(alternative) if name == "ipe" else None
    )
    assert ipe._resolve_executable("ipe.exe", None, ()) == alternative.resolve()
    monkeypatch.setattr(ipe.shutil, "which", lambda _name: None)
    with pytest.raises(IpeUnavailableError, match="was not found"):
        ipe._resolve_executable("ipe.exe", None, ())


def test_ipe_candidate_and_platform_open_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "ipe.exe"
    executable.write_bytes(b"exe")
    monkeypatch.setattr(
        ipe.shutil,
        "which",
        lambda name: str(executable) if name in {"ipe.exe", "ipe"} else None,
    )
    directories = ipe._candidate_directories({"ipe": str(executable), "other": None})
    assert tmp_path.resolve() in directories
    assert ipe._trusted_executable(str(executable)) == executable.resolve()
    assert ipe._trusted_executable("ipe") == executable.resolve()

    opened: list[str] = []
    monkeypatch.setattr(ipe.os, "startfile", opened.append)
    ipe._system_open(tmp_path / "file.png")
    assert opened and opened[0].endswith("file.png")
