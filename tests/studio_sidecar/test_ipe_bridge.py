from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.models import AssetFormat
from qbank.studio_sidecar import ipe_bridge
from qbank.studio_sidecar.ipe_bridge import (
    UnicodeSafeAssetLauncher,
    UnicodeSafeIpeRenderer,
)


def test_launcher_delegates_safe_read_actions(synthetic_bank: Path) -> None:
    context = ProjectContext.from_root(synthetic_bank)
    launcher = UnicodeSafeAssetLauncher(context)
    svg = synthetic_bank / "assets" / "OPT-SYN-0001" / "diagram-1" / "render-svg.svg"
    directory = svg.parent
    assert launcher.open_file(svg, execute=False)[0] == "system-default"
    assert launcher.open_directory(directory, execute=False)[0] == "system-default"
    assert launcher.open_url("https://example.invalid/asset", execute=False) == (
        "system-browser",
        "https://example.invalid/asset",
    )
    assert launcher.edit_file(svg, AssetFormat.SVG, execute=False)[0] == "system-default"


def test_unicode_ipe_dry_run_uses_staging_marker(
    synthetic_bank: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ProjectContext.from_root(synthetic_bank)
    source = synthetic_bank / "assets" / "OPT-SYN-0001" / "ipe-figure" / "source.ipe"
    monkeypatch.setattr(
        ipe_bridge.IpeToolchain,
        "discover",
        lambda _context: SimpleNamespace(ipe=Path("ipe.exe")),
    )
    command = UnicodeSafeAssetLauncher(context).edit_file(
        source,
        AssetFormat.IPE,
        execute=False,
    )
    assert command == ("ipe.exe", "<qbank-studio-ipe-staging>/source.ipe")


def test_unicode_ipe_edit_syncs_changed_staged_bytes(
    synthetic_bank: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = ProjectContext.from_root(synthetic_bank)
    source = synthetic_bank / "assets" / "OPT-SYN-0001" / "ipe-figure" / "source.ipe"
    changed = source.read_bytes().replace(b"</ipe>", b"<!-- bridge edit -->\n</ipe>")
    monkeypatch.setattr(
        ipe_bridge.IpeToolchain,
        "discover",
        lambda _context: SimpleNamespace(ipe=Path("ipe.exe")),
    )

    class FinishedProcess:
        def wait(self) -> int:
            return 0

    def fake_popen(command: list[str], **_kwargs: object) -> FinishedProcess:
        Path(command[1]).write_bytes(changed)
        return FinishedProcess()

    monkeypatch.setattr(ipe_bridge.subprocess, "Popen", fake_popen)
    command = UnicodeSafeAssetLauncher(context).edit_file(
        source,
        AssetFormat.IPE,
        execute=True,
    )
    assert command[0] == "ipe.exe"
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            if source.read_bytes() == changed:
                break
        except PermissionError:
            pass
        time.sleep(0.01)
    assert source.read_bytes() == changed


def test_launcher_rejects_paths_outside_repository(
    synthetic_bank: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.svg"
    outside.write_text("<svg/>", encoding="utf-8")
    launcher = UnicodeSafeAssetLauncher(ProjectContext.from_root(synthetic_bank))
    with pytest.raises(DataValidationError, match="escapes the repository"):
        launcher.open_file(outside, execute=False)
    with pytest.raises(DataValidationError, match="not a directory"):
        launcher.open_directory(
            synthetic_bank / "qbank.yaml",
            execute=False,
        )


def test_renderer_delegates_ascii_source(
    synthetic_bank: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = synthetic_bank / "assets" / "OPT-SYN-0001" / "ipe-figure" / "source.ipe"
    renderer = UnicodeSafeIpeRenderer(ProjectContext.from_root(synthetic_bank))
    expected = (SimpleNamespace(format=AssetFormat.SVG),)
    monkeypatch.setattr(renderer.delegate, "render", lambda *_args, **_kwargs: expected)
    monkeypatch.setattr(ipe_bridge, "_is_ascii_path", lambda _path: True)
    assert renderer.render(source, [AssetFormat.SVG], execute=False) == expected


def test_renderer_stages_unicode_source(
    synthetic_bank: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = synthetic_bank / "assets" / "OPT-SYN-0001" / "ipe-figure" / "source.ipe"
    renderer = UnicodeSafeIpeRenderer(ProjectContext.from_root(synthetic_bank))
    observed: list[Path] = []

    def fake_render(path: Path, *_args: object, **_kwargs: object) -> tuple[object, ...]:
        observed.append(path)
        assert path.name == "source.ipe"
        assert path.read_bytes() == source.read_bytes()
        return ()

    monkeypatch.setattr(renderer.delegate, "render", fake_render)
    monkeypatch.setattr(ipe_bridge, "_tool_compatible_path", lambda path: path)
    assert renderer.render(source, [AssetFormat.SVG], execute=False) == ()
    assert len(observed) == 1


def test_tool_path_and_sync_error_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ascii_dir = tmp_path / "ascii"
    ascii_dir.mkdir()
    monkeypatch.setattr(ipe_bridge, "_is_ascii_path", lambda _path: True)
    assert ipe_bridge._tool_compatible_path(ascii_dir) == ascii_dir.resolve()

    class BrokenProcess:
        def wait(self) -> int:
            raise OSError("process failed")

    staged = ascii_dir / "missing.ipe"
    destination = ascii_dir / "destination.ipe"
    ipe_bridge._sync_edited_ipe(
        BrokenProcess(),  # type: ignore[arg-type]
        staged,
        destination,
        b"original",
        ascii_dir,
    )
    assert "failed to synchronize" in caplog.text
    assert not ascii_dir.exists()
