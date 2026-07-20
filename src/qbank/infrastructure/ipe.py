"""Built-in Ipe editor/renderer and safe system-open adapters."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from qbank.context import ProjectContext
from qbank.domain import RenderedAsset
from qbank.errors import AssetCommandError, IpeUnavailableError
from qbank.models import AssetFormat


@dataclass(frozen=True, slots=True)
class IpeToolchain:
    """Three trusted Ipe executables resolved without a command shell."""

    ipe: Path
    iperender: Path
    ipetoipe: Path

    @classmethod
    def discover(cls, context: ProjectContext) -> IpeToolchain:
        """Resolve explicit configuration first, then PATH and Windows tool roots."""
        config = context.config.assets
        explicit = {
            "ipe.exe": config.editors.ipe.command,
            "iperender.exe": config.renderers.ipe.iperender,
            "ipetoipe.exe": config.renderers.ipe.ipetoipe,
        }
        directories = _candidate_directories(explicit)
        return cls(
            ipe=_resolve_executable("ipe.exe", explicit["ipe.exe"], directories),
            iperender=_resolve_executable(
                "iperender.exe",
                explicit["iperender.exe"],
                directories,
            ),
            ipetoipe=_resolve_executable(
                "ipetoipe.exe",
                explicit["ipetoipe.exe"],
                directories,
            ),
        )


class IpeRenderAdapter:
    """Render Ipe into PDF/SVG/PNG and fail unless every output exists."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def render(
        self,
        source: Path,
        formats: Sequence[AssetFormat],
        *,
        execute: bool,
    ) -> tuple[RenderedAsset, ...]:
        toolchain = IpeToolchain.discover(self.context)
        requested = tuple(dict.fromkeys(formats))
        unsupported = [
            item
            for item in requested
            if item not in {AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG}
        ]
        if unsupported:
            values = ", ".join(item.value for item in unsupported)
            raise AssetCommandError(f"asset_command_failed: Ipe cannot render: {values}")
        if not execute:
            return tuple(
                RenderedAsset(
                    format=item,
                    content=b"",
                    command=tuple(
                        _render_command(
                            toolchain,
                            source,
                            Path(f"render.{item.value}"),
                            item,
                        )
                    ),
                    metadata={"renderer": "ipe", "dry_run": True},
                )
                for item in requested
            )
        return self._execute(toolchain, source, requested)

    @staticmethod
    def _execute(
        toolchain: IpeToolchain,
        source: Path,
        formats: tuple[AssetFormat, ...],
    ) -> tuple[RenderedAsset, ...]:
        outputs: list[RenderedAsset] = []
        with tempfile.TemporaryDirectory(prefix=".qbank-render-", dir=source.parent) as temporary:
            temporary_root = Path(temporary)
            for format_ in formats:
                output = temporary_root / f"render.{format_.value}"
                command = _render_command(toolchain, source, output, format_)
                result = subprocess.run(
                    command,
                    cwd=source.parent,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if result.returncode or not output.is_file() or output.stat().st_size == 0:
                    details = result.stderr.strip() or "Ipe did not create a non-empty output"
                    raise AssetCommandError(
                        "asset_command_failed: "
                        f"Ipe {format_.value} render failed ({result.returncode}): {details}"
                    )
                outputs.append(
                    RenderedAsset(
                        format=format_,
                        content=output.read_bytes(),
                        command=tuple(command),
                        metadata={
                            "renderer": "ipe",
                            "source": source.name,
                        },
                    )
                )
        return tuple(outputs)


class SafeAssetLauncher:
    """Launch only repository-resolved targets through built-in adapters."""

    def __init__(self, context: ProjectContext):
        self.context = context

    def open_file(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        command = ("system-default", str(path))
        if execute:
            _system_open(path)
        return command

    def open_url(self, url: str, *, execute: bool) -> tuple[str, ...]:
        command = ("system-browser", url)
        if execute and not webbrowser.open(url):
            raise AssetCommandError("asset_command_failed: default browser rejected the URL")
        return command

    def open_directory(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        command = ("system-default", str(path))
        if execute:
            _system_open(path)
        return command

    def edit_file(
        self,
        path: Path,
        format_: AssetFormat,
        *,
        execute: bool,
    ) -> tuple[str, ...]:
        if format_ == AssetFormat.IPE:
            executable = IpeToolchain.discover(self.context).ipe
            command = (str(executable), str(path))
            if execute:
                _spawn(command, path.parent)
            return command
        configured = self.context.config.assets.editors.text.command
        if format_ == AssetFormat.TIKZ and configured is not None:
            executable = _trusted_executable(configured)
            command = (str(executable), str(path))
            if execute:
                _spawn(command, path.parent)
            return command
        return self.open_file(path, execute=execute)


def _render_command(
    toolchain: IpeToolchain,
    source: Path,
    output: Path,
    format_: AssetFormat,
) -> list[str]:
    if format_ == AssetFormat.PDF:
        return [
            str(toolchain.ipetoipe),
            "-pdf",
            "-export",
            str(source),
            str(output),
        ]
    if format_ == AssetFormat.SVG:
        return [str(toolchain.iperender), "-svg", str(source), str(output)]
    return [
        str(toolchain.iperender),
        "-png",
        "-resolution",
        "180",
        str(source),
        str(output),
    ]


def _candidate_directories(explicit: dict[str, str | None]) -> tuple[Path, ...]:
    directories: list[Path] = []
    for value in explicit.values():
        if value:
            candidate = Path(value).expanduser()
            if candidate.parent != Path("."):
                directories.append(candidate.parent.resolve())
    for name in ("ipe.exe", "ipe", "iperender.exe", "iperender"):
        found = shutil.which(name)
        if found:
            directories.append(Path(found).resolve().parent)
    for root in (Path("E:/Tool"), Path("C:/Program Files")):
        if root.is_dir():
            directories.extend(
                item for item in sorted(root.glob("ipe-*/bin"), reverse=True) if item.is_dir()
            )
    return tuple(dict.fromkeys(directories))


def _resolve_executable(
    expected: str,
    configured: str | None,
    directories: tuple[Path, ...],
) -> Path:
    if configured is not None:
        candidate = _trusted_executable(configured)
        if candidate.name.lower() != expected:
            raise IpeUnavailableError(
                f"ipe_unavailable: configured command must be {expected}: {candidate}"
            )
        return candidate
    for directory in directories:
        candidate = directory / expected
        if candidate.is_file():
            return candidate.resolve()
    alternative = shutil.which(expected.removesuffix(".exe"))
    if alternative:
        return Path(alternative).resolve()
    raise IpeUnavailableError(
        "ipe_unavailable: Ipe 7 CLI was not found; configure assets.editors.ipe.command "
        "and assets.renderers.ipe.ipetoipe/iperender"
    )


def _trusted_executable(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    found = shutil.which(value)
    if found:
        return Path(found).resolve()
    raise IpeUnavailableError(f"ipe_unavailable: configured executable not found: {value}")


def _system_open(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))
            return
        executable = "open" if sys_platform_is_macos() else "xdg-open"
        _spawn((executable, str(path)), path.parent)
    except OSError as exc:
        raise AssetCommandError(f"asset_command_failed: cannot open {path}: {exc}") from exc


def _spawn(command: tuple[str, ...], cwd: Path) -> None:
    try:
        subprocess.Popen(
            list(command),
            cwd=cwd,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise AssetCommandError(f"asset_command_failed: cannot launch {command[0]}: {exc}") from exc


def sys_platform_is_macos() -> bool:
    """Keep platform branching testable without importing a GUI library."""
    import sys

    return sys.platform == "darwin"
