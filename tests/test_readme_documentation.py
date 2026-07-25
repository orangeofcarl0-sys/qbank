"""Regression checks for the public-facing README documentation."""

from __future__ import annotations

import re
import struct
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

from qbank.codex_manifest import (
    INTEGRATION_CAPABILITIES,
    INTEGRATION_REVISION,
    MCP_RESOURCE_URIS,
    MCP_TOOL_NAMES,
)
from qbank.models import SCHEMA_VERSION, DiagnosticCode

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs" / "user-guide.md",
    ROOT / "docs" / "codex-integration.md",
    ROOT / "docs" / "compatibility-0.2.0.md",
    ROOT / "docs" / "known-limitations-0.2.0.md",
)
README_PNGS = (
    ROOT / "docs" / "assets" / "readme" / "studio-main-light.png",
    ROOT / "docs" / "assets" / "readme" / "studio-main-dark.png",
    ROOT / "docs" / "assets" / "readme" / "studio-assets-dark.png",
)
README_ZH_SVGS = (
    ROOT / "docs" / "assets" / "readme" / "data-architecture.svg",
    ROOT / "docs" / "assets" / "readme" / "safe-workflow.svg",
)
README_EN_SVGS = (
    ROOT / "docs" / "assets" / "readme" / "data-architecture.en.svg",
    ROOT / "docs" / "assets" / "readme" / "safe-workflow.en.svg",
)
README_AI_BADGE = ROOT / "docs" / "assets" / "readme" / "ai-first-badge.svg"
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
    readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    assert "<picture>" in readme
    assert "prefers-color-scheme: dark" in readme
    for image in (*README_PNGS, *README_ZH_SVGS, *README_EN_SVGS, README_AI_BADGE):
        assert image.is_file()
        assert image.stat().st_size < 800_000
    for image in (*README_PNGS, *README_ZH_SVGS):
        assert image.name in readme
    for image in (*README_PNGS, *README_EN_SVGS):
        assert image.name in readme_en

    for png in README_PNGS:
        width, height = _png_dimensions(png)
        assert width >= 1400
        assert height >= 850

    for svg in (*README_ZH_SVGS, *README_EN_SVGS, README_AI_BADGE):
        root = ElementTree.parse(svg).getroot()
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        assert root.find("svg:title", namespace) is not None
        assert root.find("svg:desc", namespace) is not None


def test_readme_does_not_present_unimplemented_mcp_command() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "codex mcp add qbank" not in readme
    assert "ZJU841" not in readme


def test_readmes_disclose_ai_coding_and_acknowledge_current_studio() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")
    for text in (readme, readme_en):
        assert "coding agent" in text
        assert "docs/assets/readme/ai-first-badge.svg" in text
        assert "apps/studio/THIRD_PARTY_NOTICES.md" in text
        assert "src/qbank/resources/desktop/THIRD_PARTY_NOTICES.md" in text
        assert "https://github.com/tauri-apps/tauri" in text
        assert "https://github.com/moodle/moodle" in text
        assert "immutable release baseline" not in text
        assert "不可变发布基线" not in text


def test_modern_readme_capture_uses_tauri_fixture_and_legacy_script_is_labeled() -> None:
    capture_spec = (
        ROOT / "apps" / "studio" / "tests" / "browser" / "visual-acceptance.spec.ts"
    ).read_text(encoding="utf-8")
    for expected in (
        "/?fixture=1",
        "studio-light.png",
        "studio-dark.png",
        "studio-asset-menu.png",
    ):
        assert expected in capture_spec

    completed = subprocess.run(
        [sys.executable, "scripts/capture-ui.py", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Legacy" in completed.stdout
    assert "--scale {1,1.25}" in completed.stdout


def test_020_compatibility_document_freezes_runtime_manifests() -> None:
    texts = tuple(
        (ROOT / "docs" / locale / "compatibility-0.2.0.md").read_text(encoding="utf-8")
        for locale in ("zh-CN", "en")
    )
    assert SCHEMA_VERSION == "1.0"
    assert INTEGRATION_REVISION == 3
    assert len(MCP_TOOL_NAMES) == 19
    assert len(MCP_RESOURCE_URIS) == 8
    for value in (
        *MCP_TOOL_NAMES,
        *MCP_RESOURCE_URIS,
        *(item.name for item in INTEGRATION_CAPABILITIES),
        *(item.value for item in DiagnosticCode),
    ):
        assert all(value in text for text in texts)


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])
