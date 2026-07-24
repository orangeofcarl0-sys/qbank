"""Documentation lifecycle and synchronization-gate tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_documentation_sync_gate_passes_repository_contract() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/check_docs_sync.py", "--skip-examples"],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS cli-reference: 53 public commands documented" in result.stdout
    assert "PASS manifest-capability-docs: 22 capabilities documented" in result.stdout
    assert "docs-sync: PASS" in result.stdout


def test_documentation_gate_is_part_of_ci_and_release_preparation() -> None:
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    skill = (root / ".agents/skills/release-preparation/SKILL.md").read_text(encoding="utf-8")
    release_script = (
        root / ".agents/skills/release-preparation/scripts/prepare_release.py"
    ).read_text(encoding="utf-8")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")

    for text in (workflow, skill, release_script, agents):
        assert "scripts/check_docs_sync.py" in text


def test_feature_template_contains_required_maintenance_contract() -> None:
    root = Path(__file__).parents[1]
    template = (root / "docs/features/_template.md").read_text(encoding="utf-8")
    headings = (
        "用户目标",
        "使用入口",
        "CLI / Studio / MCP 对应关系",
        "数据与配置变化",
        "安全和失败行为",
        "兼容性与迁移",
        "测试与验收",
        "当前限制",
    )

    assert all(f"## {heading}" in template for heading in headings)
