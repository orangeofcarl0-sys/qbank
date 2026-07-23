"""Windows path-boundary coverage that does not require symlink privileges."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.infrastructure.assets import FileAssetRepository
from qbank.mcp.adapter import QbankMcpAdapter
from qbank.transaction import MutationTransaction
from qbank.utils import is_reparse_point

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point coverage")


def _junction(link: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.fail(f"unable to create test junction: {result.stdout} {result.stderr}")
    assert is_reparse_point(link)


def test_mcp_package_root_rejects_traversal_absolute_and_unc(
    project: tuple[Path, object],
) -> None:
    root, _ = project
    adapter = QbankMcpAdapter(ProjectContext.from_root(root))
    for value in ("../outside", str(root.resolve()), r"\\server\share\package"):
        with pytest.raises(DataValidationError, match="contained relative"):
            adapter._package_root(value)


def test_package_root_is_case_insensitive_without_escaping(
    project: tuple[Path, object],
) -> None:
    root, _ = project
    package = root / "IMPORT"
    package.mkdir()
    resolved = QbankMcpAdapter(ProjectContext.from_root(root))._package_root("import")
    assert resolved.samefile(package)


def test_junction_escape_is_rejected_without_symlink_privilege(
    project: tuple[Path, object],
    tmp_path: Path,
) -> None:
    root, _ = project
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "incoming"
    _junction(link, outside)
    try:
        adapter = QbankMcpAdapter(ProjectContext.from_root(root))
        with pytest.raises(DataValidationError, match="reparse point"):
            adapter._package_root("incoming")
    finally:
        os.rmdir(link)


def test_asset_target_replacement_with_junction_cannot_write_outside(
    project: tuple[Path, object],
    tmp_path: Path,
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    safe = context.paths.assets / "SAFE"
    safe.mkdir()
    target = safe / "asset-1" / "render.bin"
    transaction = MutationTransaction.for_context(context)
    transaction.write_bytes(target, b"blocked")
    safe.rmdir()
    outside = tmp_path / "outside-target"
    outside.mkdir()
    _junction(safe, outside)
    try:
        with pytest.raises(DataValidationError, match="reparse point"):
            transaction.commit()
        assert not (outside / "asset-1" / "render.bin").exists()
        with pytest.raises(DataValidationError, match="reparse point"):
            FileAssetRepository(context).location("SAFE", "asset-1")
    finally:
        os.rmdir(safe)
