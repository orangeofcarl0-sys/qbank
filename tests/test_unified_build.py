"""Monorepo structure, version, and orchestration contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from qbank import __version__
from qbank.studio_sidecar import PROTOCOL_VERSION

ROOT = Path(__file__).parents[1]


def test_modern_studio_and_legacy_qt_are_one_product_tree() -> None:
    assert (ROOT / "apps/studio/src").is_dir()
    assert (ROOT / "apps/studio/src-tauri").is_dir()
    assert (ROOT / "apps/studio/tests").is_dir()
    assert (ROOT / "src/qbank/studio_sidecar").is_dir()
    assert (ROOT / "src/qbank/legacy_qt").is_dir()
    assert not (ROOT / "src/qbank/desktop").exists()
    assert (ROOT / "protocol/studio-protocol-v1.json").is_file()


def test_python_and_display_versions_share_the_beta_line() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "apps/studio/package.json").read_text(encoding="utf-8"))
    tauri = json.loads((ROOT / "apps/studio/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert __version__ == project["project"]["version"] == "0.3.0b2"
    assert package["version"] == tauri["version"] == "0.3.0-beta.2"
    assert PROTOCOL_VERSION == "1.0"


def test_sdist_excludes_generated_and_dependency_trees() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = set(project["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"])
    assert {
        "/.venv",
        "/apps/studio/dist",
        "/apps/studio/node_modules",
        "/apps/studio/playwright-report",
        "/apps/studio/src-tauri/binaries",
        "/apps/studio/src-tauri/target",
        "/apps/studio/test-results",
        "/build",
    } <= excluded


def test_sidecar_reuses_qbank_services_without_domain_copies() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "src/qbank/studio_sidecar").glob("*.py"))
    )
    assert "from qbank.application" in source
    assert "from qbank.bootstrap" in source
    for duplicate in (
        "class Question(",
        "class Paper(",
        "class MutationTransaction(",
        "class SQLiteSearchIndex(",
        "class MarkdownQuestionRepository(",
    ):
        assert duplicate not in source


def test_change_impact_map_covers_every_monorepo_surface() -> None:
    impact = json.loads((ROOT / "scripts/change-impact.json").read_text(encoding="utf-8"))
    assert set(impact["scopes"]) == {
        "core",
        "legacy",
        "sidecar",
        "studio",
        "build",
        "docs",
    }
    assert set(impact["integrationTriggers"]) == {
        "protocol",
        "writing",
        "editor",
        "permissions",
        "installation",
    }
    assert "gitCommit" in impact["evidenceReuse"]["requiredBindings"]
    assert "artifactSha256" in impact["evidenceReuse"]["requiredBindings"]


def test_root_orchestrators_have_stable_help() -> None:
    for script, commands in (
        ("scripts/check.py", ("fast", "integration", "release")),
        ("scripts/build.py", ("wheel", "studio", "all")),
    ):
        result = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert all(command in result.stdout for command in commands)
