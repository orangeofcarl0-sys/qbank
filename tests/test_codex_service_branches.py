"""Codex Skill and executable-probe edge-state coverage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import qbank.services.codex as codex
from qbank.context import ProjectContext
from qbank.errors import DataValidationError


def test_skill_endpoint_backup_and_change_classification(
    project: tuple[Path, Any], tmp_path: Path
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    user = codex._SkillSelection(scope="user", home=tmp_path, name="qbank")
    source, label, destination = codex._skill_endpoints(context, user)
    assert source == root / ".agents" / "skills" / "qbank"
    assert label == str(source)
    assert destination == tmp_path / ".agents" / "skills" / "qbank"

    digitize = codex._SkillSelection(scope="project", home=None, name="qbank-digitize")
    packaged, label, destination = codex._skill_endpoints(context, digitize)
    assert isinstance(packaged, dict) and "SKILL.md" in packaged
    assert "qbank-digitize" in label and destination.name == "qbank-digitize"
    assert "qbank-digitize" in str(codex._backup_destination(context, digitize))
    invalid = codex._SkillSelection(
        scope=cast(codex.SkillScope, "invalid"), home=None, name="qbank"
    )
    with pytest.raises(DataValidationError, match="unsupported Skill scope"):
        codex._skill_endpoints(context, invalid)

    changes = codex._skill_changes(
        {"same": b"x", "modified": b"old", "deleted": b"gone"},
        {"same": b"x", "modified": b"new", "added": b"fresh"},
    )
    assert {change.action for change in changes} == {"add", "modify", "delete"}


def test_skill_checks_report_missing_files_and_non_directories(
    project: tuple[Path, Any], tmp_path: Path
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    missing = tmp_path / "missing"
    assert codex._skill_frontmatter_check(missing / "SKILL.md").status == "FAIL"
    assert codex._skill_sync_check("optional", missing, {}, optional=True).status == "PASS"
    assert codex._skill_sync_check("required", missing, {}, optional=False).status == "FAIL"

    file_path = tmp_path / "skill-file"
    file_path.write_text("not a directory", encoding="utf-8")
    assert codex._skill_sync_check("file", file_path, {}, optional=True).status == "WARN"
    assert codex._safe_project_skill_contents(file_path) == codex.canonical_skill_contents()
    with pytest.raises(DataValidationError, match="repository Skill is missing"):
        codex._validate_skill_source(context, missing)
    outside = root.parent / f"{root.name}-outside-skill"
    outside.mkdir(exist_ok=True)
    (outside / "SKILL.md").write_text("skill", encoding="utf-8")
    with pytest.raises(DataValidationError, match="escapes project root"):
        codex._validate_skill_source(context, outside)
    with pytest.raises(DataValidationError, match="not a directory"):
        codex._validate_destination(file_path)


def test_codex_probe_selects_first_runnable_candidate(
    project: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    monkeypatch.setattr(
        codex,
        "_codex_cli_candidates",
        lambda _context: [("bad-codex", "bad"), ("good-codex", "good"), ("later", "later")],
    )
    results = iter(
        (
            SimpleNamespace(returncode=2, stdout="", stderr="bad version"),
            SimpleNamespace(returncode=0, stdout="codex 1.0", stderr=""),
            SimpleNamespace(returncode=0, stdout="codex 2.0", stderr=""),
        )
    )
    monkeypatch.setattr(codex.subprocess, "run", lambda *_args, **_kwargs: next(results))
    candidates, selected = codex.probe_codex_cli(context)
    assert selected == "good-codex"
    assert [candidate.status for candidate in candidates] == ["failed", "ready", "ready"]
    assert [candidate.selected for candidate in candidates] == [False, True, False]
