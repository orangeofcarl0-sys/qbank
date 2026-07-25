"""Unicode-safe adapters around qbank's trusted Ipe infrastructure ports."""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path

from qbank.application import AssetApplicationService
from qbank.bootstrap import ProjectServices
from qbank.context import ProjectContext
from qbank.domain import RenderedAsset
from qbank.errors import AssetCommandError, DataValidationError
from qbank.infrastructure import IpeRenderAdapter, SafeAssetLauncher
from qbank.infrastructure.ipe import IpeToolchain
from qbank.models import AssetFormat
from qbank.utils import atomic_write_bytes

LOGGER = logging.getLogger("qbank-studio-sidecar.ipe")


def with_unicode_safe_assets(
    context: ProjectContext,
    services: ProjectServices,
) -> ProjectServices:
    """Replace only the external Ipe ports while retaining qbank asset use cases."""
    current = services.assets
    assets = AssetApplicationService(
        repository=current.repository,
        inputs=current.inputs,
        renderer=UnicodeSafeIpeRenderer(context),
        launcher=UnicodeSafeAssetLauncher(context),
        lock=current.lock,
    )
    return ProjectServices(
        repository=services.repository,
        questions=services.questions,
        mutations=services.mutations,
        diagnostics=services.diagnostics,
        renderer=services.renderer,
        assets=assets,
        tags=services.tags,
        views=services.views,
        history=services.history,
        studio=services.studio,
        studio_project=services.studio_project,
    )


class UnicodeSafeIpeRenderer:
    """Stage Ipe sources when its Windows CLI cannot consume a Unicode path."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.delegate = IpeRenderAdapter(context)

    def render(
        self,
        source: Path,
        formats: Sequence[AssetFormat],
        *,
        execute: bool,
    ) -> tuple[RenderedAsset, ...]:
        contained = _contained_file(self.context, source)
        if _is_ascii_path(contained):
            return self.delegate.render(contained, formats, execute=execute)
        with tempfile.TemporaryDirectory(prefix="qbank-studio-ipe-") as temporary:
            actual_root = Path(temporary)
            tool_root = _tool_compatible_path(actual_root)
            staged = actual_root / "source.ipe"
            shutil.copyfile(contained, staged)
            return self.delegate.render(
                tool_root / staged.name,
                formats,
                execute=execute,
            )


class UnicodeSafeAssetLauncher:
    """Delegate safe opens and bridge Ipe edits across Unicode Windows paths."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.delegate = SafeAssetLauncher(context)

    def open_file(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        return self.delegate.open_file(_contained_file(self.context, path), execute=execute)

    def open_url(self, url: str, *, execute: bool) -> tuple[str, ...]:
        return self.delegate.open_url(url, execute=execute)

    def open_directory(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        contained = _contained_directory(self.context, path)
        return self.delegate.open_directory(contained, execute=execute)

    def edit_file(
        self,
        path: Path,
        format_: AssetFormat,
        *,
        execute: bool,
    ) -> tuple[str, ...]:
        contained = _contained_file(self.context, path)
        if format_ != AssetFormat.IPE or _is_ascii_path(contained):
            return self.delegate.edit_file(contained, format_, execute=execute)
        executable = IpeToolchain.discover(self.context).ipe
        if not execute:
            return (str(executable), "<qbank-studio-ipe-staging>/source.ipe")
        actual_root = Path(tempfile.mkdtemp(prefix="qbank-studio-ipe-edit-"))
        try:
            tool_root = _tool_compatible_path(actual_root)
            staged = actual_root / "source.ipe"
            original = contained.read_bytes()
            staged.write_bytes(original)
            command = (str(executable), str(tool_root / staged.name))
            process = subprocess.Popen(
                list(command),
                cwd=tool_root,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            shutil.rmtree(actual_root, ignore_errors=True)
            raise
        monitor = threading.Thread(
            target=_sync_edited_ipe,
            args=(process, staged, contained, original, actual_root),
            name="qbank-studio-ipe-sync",
            daemon=True,
        )
        monitor.start()
        return command


def _sync_edited_ipe(
    process: subprocess.Popen[bytes],
    staged: Path,
    destination: Path,
    original: bytes,
    temporary_root: Path,
) -> None:
    try:
        process.wait()
        content = staged.read_bytes()
        if content != original:
            atomic_write_bytes(destination, content)
            LOGGER.info("synchronized edited Ipe source: %s", destination)
    except (OSError, ValueError) as exc:
        LOGGER.error("failed to synchronize edited Ipe source: %s", exc)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def _contained_file(context: ProjectContext, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    _require_contained(context, resolved)
    if not resolved.is_file():
        raise DataValidationError(f"asset path is not a file: {resolved}")
    return resolved


def _contained_directory(context: ProjectContext, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    _require_contained(context, resolved)
    if not resolved.is_dir():
        raise DataValidationError(f"asset path is not a directory: {resolved}")
    return resolved


def _require_contained(context: ProjectContext, path: Path) -> None:
    try:
        path.relative_to(context.root.resolve(strict=True))
    except ValueError as exc:
        raise DataValidationError(f"asset path escapes the repository: {path}") from exc


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _tool_compatible_path(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if _is_ascii_path(resolved):
        return resolved
    if os.name != "nt":
        raise AssetCommandError("asset_command_failed: Ipe staging path is not ASCII-compatible")
    short = _windows_short_path(resolved)
    if not _is_ascii_path(short):
        raise AssetCommandError(
            "asset_command_failed: Windows could not provide an ASCII Ipe staging path"
        )
    return short


def _windows_short_path(path: Path) -> Path:
    get_short_path = ctypes.windll.kernel32.GetShortPathNameW
    get_short_path.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    get_short_path.restype = ctypes.c_uint
    required = get_short_path(str(path), None, 0)
    if required == 0:
        raise AssetCommandError(
            "asset_command_failed: GetShortPathNameW rejected the Ipe staging path"
        )
    buffer = ctypes.create_unicode_buffer(required)
    written = get_short_path(str(path), buffer, required)
    if written == 0 or written >= required:
        raise AssetCommandError(
            "asset_command_failed: GetShortPathNameW could not encode the Ipe staging path"
        )
    return Path(buffer.value)
