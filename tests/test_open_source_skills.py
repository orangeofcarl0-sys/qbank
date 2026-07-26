from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = ROOT / ".agents/skills/oss-readiness/scripts/audit.py"
RELEASE_SCRIPT = ROOT / ".agents/skills/release-preparation/scripts/prepare_release.py"
PUBLISH_SCRIPT = ROOT / ".agents/skills/github-publish/scripts/publish.py"


def _run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git_repository(path: Path) -> None:
    _run("git", "init", cwd=path)
    _run("git", "config", "user.name", "qbank test", cwd=path)
    _run("git", "config", "user.email", "test@example.com", cwd=path)
    (path / ".gitignore").write_text("build/\n", encoding="utf-8")
    (path / "LICENSE").write_text("Synthetic test license\n", encoding="utf-8")
    (path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (path / "pyproject.toml").write_text(
        "[build-system]\nrequires=[]\nbuild-backend='fixture'\n"
        "[project]\nname='fixture'\nversion='0.1.0'\ndependencies=[]\n",
        encoding="utf-8",
    )


def _commit(path: Path, message: str) -> None:
    _run("git", "add", ".", cwd=path)
    _run("git", "commit", "-m", message, cwd=path)


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def test_oss_audit_detects_and_redacts_sensitive_surfaces(tmp_path: Path) -> None:
    _git_repository(tmp_path)
    fake_secret = "AKIA" + "A" * 16
    (tmp_path / "historic.txt").write_text(f"token={fake_secret}\n", encoding="utf-8")
    _commit(tmp_path, "add historical fixture")
    (tmp_path / "historic.txt").unlink()
    (tmp_path / "machine.txt").write_text(
        "local="
        + "C:"
        + "\\Users\\fixture\\private\\tool.exe\nunc="
        + "\\\\server\\share\\private\\file.txt\n",
        encoding="utf-8",
    )
    question = tmp_path / "questions" / "private" / "EXAM-2020-0001.md"
    question.parent.mkdir(parents=True)
    question.write_text("copyrighted fixture\n", encoding="utf-8")
    font = tmp_path / "vendor" / "unknown.ttf"
    font.parent.mkdir()
    font.write_bytes(b"unlicensed-font-fixture")
    _commit(tmp_path, "replace with current fixtures")

    output = tmp_path / "build" / "oss-audit"
    result = _run(
        sys.executable,
        str(AUDIT_SCRIPT),
        "--root",
        str(tmp_path),
        "--output",
        str(output),
        "--skip-external",
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 3
    expected = {
        "readiness-report.md",
        "findings.json",
        "tracked-files.txt",
        "distributable-files.txt",
        "license-report.json",
        "secret-scan-report.json",
    }
    assert expected <= {path.name for path in output.iterdir()}
    findings_text = (output / "findings.json").read_text(encoding="utf-8")
    findings = json.loads(findings_text)["findings"]
    categories = {item["category"] for item in findings}
    assert {"secret", "absolute_path", "private_question_data", "asset_license"} <= categories
    assert fake_secret not in findings_text
    assert fake_secret not in (output / "secret-scan-report.json").read_text(encoding="utf-8")
    assert any(item["source"] == "git-history" for item in findings if item["category"] == "secret")


def test_oss_audit_is_idempotent(tmp_path: Path) -> None:
    _git_repository(tmp_path)
    _commit(tmp_path, "initial")
    output = tmp_path / "build" / "oss-audit"
    command = (
        sys.executable,
        str(AUDIT_SCRIPT),
        "--root",
        str(tmp_path),
        "--output",
        str(output),
        "--skip-external",
    )
    first = _run(*command, cwd=tmp_path, check=False)
    snapshots = {path.name: path.read_bytes() for path in output.iterdir() if path.is_file()}
    second = _run(*command, cwd=tmp_path, check=False)
    assert first.returncode == second.returncode
    assert snapshots == {
        path.name: path.read_bytes() for path in output.iterdir() if path.is_file()
    }


def test_archive_manifests_match_wheel_and_sdist(tmp_path: Path) -> None:
    module = _load_module(RELEASE_SCRIPT, "qbank_release_preparation_test")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheel = artifacts / "fixture-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("fixture/__init__.py", "")
        archive.writestr("fixture-0.1.0.dist-info/METADATA", "Name: fixture\n")
    sdist = artifacts / "fixture-0.1.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        content = b"[project]\nname='fixture'\n"
        info = tarfile.TarInfo("fixture-0.1.0/pyproject.toml")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
        demo = tarfile.TarInfo("fixture-0.1.0/examples/public-demo/questions/demo/DEMO-GEO-0001.md")
        demo.size = 0
        archive.addfile(demo, io.BytesIO())
        studio_fixture = tarfile.TarInfo(
            "fixture-0.1.0/apps/studio/fixtures/synthetic-bank/questions/demo/DEMO-0002.md"
        )
        studio_fixture.size = 0
        archive.addfile(studio_fixture, io.BytesIO())

    checks, manifests = module._inspect_archives(artifacts)

    assert all(check.status == "passed" for check in checks)
    assert manifests[wheel.name] == [
        "fixture-0.1.0.dist-info/METADATA",
        "fixture/__init__.py",
    ]
    assert manifests[sdist.name] == [
        "fixture-0.1.0/apps/studio/fixtures/synthetic-bank/questions/demo/DEMO-0002.md",
        "fixture-0.1.0/examples/public-demo/questions/demo/DEMO-GEO-0001.md",
        "fixture-0.1.0/pyproject.toml",
    ]


def _green_release_fixture(path: Path) -> None:
    _git_repository(path)
    (path / "build" / "release" / "artifacts").mkdir(parents=True)
    (path / "build" / "release" / "release-plan.json").write_text(
        json.dumps(
            {
                "decision": "GREEN",
                "oss_readiness": "GREEN",
                "version": "0.1.0",
                "tag": "v0.1.0",
                "artifacts": {"fixture.whl": "0" * 64},
            }
        ),
        encoding="utf-8",
    )
    (path / "build" / "release" / "checksums.txt").write_text(
        f"{'0' * 64}  fixture.whl\n", encoding="utf-8"
    )
    _commit(path, "initial")


def test_publish_prepare_is_read_only_and_idempotent(tmp_path: Path) -> None:
    _green_release_fixture(tmp_path)
    command = (
        sys.executable,
        str(PUBLISH_SCRIPT),
        "prepare",
        "--root",
        str(tmp_path),
        "--repository",
        "example/qbank",
        "--tag",
        "v0.1.0",
        "--visibility",
        "public",
    )
    before = _run("git", "tag", "--list", cwd=tmp_path).stdout
    first = _run(*command, cwd=tmp_path, check=False)
    plan = (tmp_path / "build" / "release" / "publish-plan.json").read_bytes()
    second = _run(*command, cwd=tmp_path, check=False)

    assert first.returncode == second.returncode == 0
    assert before == _run("git", "tag", "--list", cwd=tmp_path).stdout
    assert plan == (tmp_path / "build" / "release" / "publish-plan.json").read_bytes()
    payload = json.loads(plan)
    assert payload["remote_writes"] is False
    assert "checksums.txt" in payload["attachments"]


def test_publish_commit_requires_explicit_confirmation(tmp_path: Path) -> None:
    _green_release_fixture(tmp_path)
    prepare_command = (
        sys.executable,
        str(PUBLISH_SCRIPT),
        "prepare",
        "--root",
        str(tmp_path),
        "--repository",
        "example/qbank",
        "--tag",
        "v0.1.0",
        "--visibility",
        "public",
    )
    assert _run(*prepare_command, cwd=tmp_path, check=False).returncode == 0
    commit_command = list(prepare_command)
    commit_command[2] = "commit"
    result = _run(*commit_command, cwd=tmp_path, check=False)

    assert result.returncode == 5
    assert "--confirm-publish is required" in result.stderr
    assert _run("git", "tag", "--list", cwd=tmp_path).stdout == ""


def test_public_docs_and_examples_have_no_machine_paths() -> None:
    pattern = re.compile(
        r"(?i)(?:[A-Z]:[\\/](?:Users|project|Program Files|tools)[\\/]|"
        r"\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+\\[A-Za-z0-9$._-])"
    )
    paths = [ROOT / "README.md"]
    paths.extend((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    paths.extend(
        path
        for path in (ROOT / "examples").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    assert not {
        str(path.relative_to(ROOT)): pattern.findall(
            path.read_text(encoding="utf-8", errors="ignore")
        )
        for path in paths
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    }


def test_open_source_skills_are_discoverable() -> None:
    yaml = YAML(typ="safe")
    for name in ("oss-readiness", "release-preparation", "github-publish", "open-source-publish"):
        skill_dir = ROOT / ".agents" / "skills" / name
        skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert skill.startswith("---\n")
        frontmatter = yaml.load(skill.split("---\n", 2)[1])
        assert frontmatter["name"] == name
        assert frontmatter["description"].strip()
        interface = yaml.load((skill_dir / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        assert f"${name}" in interface["interface"]["default_prompt"]


def test_public_demo_validates_without_real_question_data() -> None:
    environment_command = (
        sys.executable,
        "-m",
        "qbank",
        "validate",
        "--format",
        "json",
    )
    result = subprocess.run(
        environment_command,
        cwd=ROOT / "examples" / "public-demo",
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["summary"]["questions"] == 1
    assert payload["summary"]["errors"] == 0
