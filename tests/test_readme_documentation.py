"""Regression checks for the public-facing README documentation."""

from __future__ import annotations

import re
import struct
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs" / "user-guide.md",
    ROOT / "docs" / "codex-integration.md",
)
README_IMAGES = (
    ROOT / "docs" / "assets" / "readme" / "studio-main-light.png",
    ROOT / "docs" / "assets" / "readme" / "studio-main-dark.png",
    ROOT / "docs" / "assets" / "readme" / "studio-assets-dark.png",
    ROOT / "docs" / "assets" / "readme" / "data-architecture.svg",
    ROOT / "docs" / "assets" / "readme" / "safe-workflow.svg",
)
MARKDOWN_TARGET = re.compile(r"!?(?:\[[^]]*\])\(([^)]+)\)")
HTML_TARGET = re.compile(r'(?:src|srcset)="([^"]+)"')


def test_documentation_local_targets_exist() -> None:
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        targets = MARKDOWN_TARGET.findall(text) + HTML_TARGET.findall(text)
        for raw_target in targets:
            target = raw_target.split(maxsplit=1)[0].split("#", maxsplit=1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (document.parent / target).resolve()
            assert resolved.exists(), f"broken local link in {document}: {raw_target}"


def test_readme_visual_assets_are_accessible_and_bounded() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<picture>" in readme
    assert "prefers-color-scheme: dark" in readme
    for image in README_IMAGES:
        assert image.is_file()
        assert image.stat().st_size < 800_000
        assert image.name in readme

    for png in (path for path in README_IMAGES if path.suffix == ".png"):
        width, height = _png_dimensions(png)
        assert width >= 1600
        assert height >= 900

    for svg in (path for path in README_IMAGES if path.suffix == ".svg"):
        root = ElementTree.parse(svg).getroot()
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        assert root.find("svg:title", namespace) is not None
        assert root.find("svg:desc", namespace) is not None


def test_readme_does_not_present_unimplemented_mcp_command() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "codex mcp add qbank" not in readme
    assert "ZJU841" not in readme


def test_capture_script_exposes_deterministic_asset_state() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/capture-ui.py", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "assets" in completed.stdout
    assert "--scale {1,1.25}" in completed.stdout


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])
