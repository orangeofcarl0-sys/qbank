#!/usr/bin/env python3
"""Build and verify local release artifacts without remote writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REQUIRED_README_TOPICS = {
    "positioning": ("定位", "positioning"),
    "features": ("功能", "features"),
    "installation": ("安装", "installation"),
    "quick_start": ("快速开始", "quick start"),
    "studio": ("studio",),
    "cli": ("cli", "命令行"),
    "codex_skill": ("codex skill", "codex"),
    "mcp_status": ("mcp",),
    "license": ("许可证", "license"),
    "limitations": ("限制", "limitations"),
}
FORBIDDEN_ARCHIVE_PARTS = (
    "/questions/",
    "integration-pilot",
    "/build/",
    "/.qbank/",
    "index.sqlite",
    "/.git/",
    "2005-2022",
)
QUALITY_GATES = (
    ("ruff-format", ["ruff", "format", "--check", "."]),
    ("ruff", ["ruff", "check", "."]),
    ("pyright", ["pyright"]),
    ("mypy", ["mypy", "src/qbank"]),
    ("import-linter", ["lint-imports"]),
    ("deptry", ["deptry", "."]),
    (
        "pytest",
        [
            "pytest",
            "--cov=qbank",
            "--cov-branch",
            "--cov-fail-under=0",
            "--cov-report=json:build/release/coverage.json",
        ],
    ),
    (
        "branch-coverage",
        ["python", "scripts/check_branch_coverage.py", "build/release/coverage.json"],
    ),
    ("pip-check", ["python", "-m", "pip", "check"]),
    ("pip-audit", ["pip-audit"]),
)


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _run(
    root: Path,
    args: list[str],
    *,
    timeout: int = 900,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def _python(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def _last_line(result: subprocess.CompletedProcess[str]) -> str:
    lines = [
        line.strip() for line in (result.stdout + "\n" + result.stderr).splitlines() if line.strip()
    ]
    if not lines:
        return f"exit {result.returncode}"
    selected = lines[-1:] if result.returncode == 0 else lines[-5:]
    return " | ".join(selected)[:1000]


def _git(root: Path, *args: str) -> str:
    result = _run(root, ["git", *args], timeout=30)
    return result.stdout.strip() if result.returncode == 0 else ""


def _metadata(root: Path) -> tuple[str, str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    return str(project["name"]), str(project["version"])


def _read_audit(root: Path) -> tuple[str, Check]:
    path = root / "build" / "oss-audit" / "findings.json"
    if not path.is_file():
        return "MISSING", Check("oss-readiness", "failed", "run $oss-readiness first")
    try:
        decision = str(json.loads(path.read_text(encoding="utf-8"))["decision"])
    except (OSError, KeyError, json.JSONDecodeError):
        return "INVALID", Check("oss-readiness", "failed", "audit report is invalid")
    status = "passed" if decision == "GREEN" else "failed"
    return decision, Check("oss-readiness", status, f"audit decision is {decision}")


def _check_readme(root: Path) -> list[Check]:
    text = (root / "README.md").read_text(encoding="utf-8")
    lowered = text.lower()
    checks: list[Check] = []
    missing = [
        name
        for name, aliases in REQUIRED_README_TOPICS.items()
        if not any(alias in lowered for alias in aliases)
    ]
    checks.append(
        Check(
            "readme-sections",
            "passed" if not missing else "failed",
            "all required topics present" if not missing else "missing: " + ", ".join(missing),
        )
    )
    unsafe = re.findall(
        r"(?i)(?:[A-Z]:[\\/](?:Users|project|Program Files|tools)[\\/][^\s`'\"<>]+|"
        r"\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+"
        r"(?:\\[A-Za-z0-9$._-][^\s\\]*)+|"
        r"integration-pilot|2005\D*2022)",
        text,
    )
    checks.append(
        Check(
            "readme-public-safety",
            "passed" if not unsafe else "failed",
            "no machine paths or private datasets"
            if not unsafe
            else f"{len(unsafe)} unsafe references",
        )
    )
    return checks


def _run_quality_gates(root: Path, skip: bool) -> list[Check]:
    if skip:
        return [Check("quality-gates", "failed", "skipped by request")]
    checks: list[Check] = []
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONPATH"] = str(root / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    for name, command in QUALITY_GATES:
        executable = command[0]
        if executable == "python":
            resolved = sys.executable
        else:
            sibling = Path(sys.executable).parent / (
                f"{executable}.exe" if os.name == "nt" else executable
            )
            resolved = str(sibling) if sibling.is_file() else shutil.which(executable)
        if resolved is None:
            checks.append(Check(name, "failed", f"required command not found: {executable}"))
            continue
        actual = [resolved, *command[1:]]
        try:
            result = _run(root, actual, env=environment)
        except subprocess.TimeoutExpired:
            checks.append(Check(name, "failed", "timed out"))
            continue
        checks.append(
            Check(name, "passed" if result.returncode == 0 else "failed", _last_line(result))
        )
    return checks


def _compatibility_checks(root: Path, version: str) -> list[Check]:
    environment = os.environ.copy()
    source_path = str(root / "src")
    environment["PYTHONPATH"] = source_path + os.pathsep + environment.get("PYTHONPATH", "")
    commands = [
        (
            "package-version",
            [
                sys.executable,
                "-c",
                f"import qbank; assert qbank.__version__ == {version!r}",
            ],
        ),
        ("cli-help", [sys.executable, "-m", "qbank", "--help"]),
    ]
    commands.extend(
        (
            f"schema:{kind}",
            [sys.executable, "-m", "qbank", "schema", "--kind", kind, "--format", "json"],
        )
        for kind in ("question", "paper", "patch", "asset", "asset-package")
    )
    checks: list[Check] = []
    for name, command in commands:
        result = _run(root, command, timeout=120, env=environment)
        checks.append(
            Check(name, "passed" if result.returncode == 0 else "failed", _last_line(result))
        )
    contract_files = [
        root / "schemas" / f"{name}.schema.json"
        for name in ("question", "paper", "patch", "asset", "asset-package")
    ]
    missing = [path.name for path in contract_files if not path.is_file()]
    checks.append(
        Check(
            "public-contract-files",
            "passed" if not missing else "failed",
            "all public schemas present" if not missing else "missing: " + ", ".join(missing),
        )
    )
    return checks


def _build(root: Path, artifacts: Path, skip: bool) -> list[Check]:
    if skip:
        return [Check("build", "failed", "skipped by request")]
    artifacts.mkdir(parents=True, exist_ok=True)
    for old in artifacts.iterdir():
        if old.is_file() and (old.suffix == ".whl" or old.name.endswith(".tar.gz")):
            old.unlink()
    with tempfile.TemporaryDirectory(prefix="qbank-build-") as temp:
        build_venv = Path(temp) / "build-venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(build_venv)
        python = _python(build_venv)
        install = _run(root, [str(python), "-m", "pip", "install", "build>=1,<2"], timeout=600)
        if install.returncode != 0:
            return [Check("build-environment", "failed", _last_line(install))]
        result = _run(
            root,
            [str(python), "-m", "build", "--outdir", str(artifacts), str(root)],
            timeout=900,
        )
        if result.returncode != 0:
            return [
                Check("build-environment", "passed", "isolated builder created"),
                Check("build", "failed", _last_line(result)),
            ]
    wheels = sorted(artifacts.glob("*.whl"))
    sdists = sorted(artifacts.glob("*.tar.gz"))
    return [
        Check("build-environment", "passed", "isolated builder created"),
        Check(
            "wheel", "passed" if len(wheels) == 1 else "failed", f"{len(wheels)} wheel artifact(s)"
        ),
        Check(
            "sdist", "passed" if len(sdists) == 1 else "failed", f"{len(sdists)} sdist artifact(s)"
        ),
    ]


def _members(path: Path) -> list[str]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return sorted(archive.namelist())
    with tarfile.open(path) as archive:
        return sorted(archive.getnames())


def _inspect_archives(artifacts: Path) -> tuple[list[Check], dict[str, list[str]]]:
    manifests: dict[str, list[str]] = {}
    checks: list[Check] = []
    for path in sorted(artifacts.glob("*")):
        if path.suffix != ".whl" and not path.name.endswith(".tar.gz"):
            continue
        try:
            members = _members(path)
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            checks.append(
                Check(f"archive:{path.name}", "failed", f"unreadable: {type(exc).__name__}")
            )
            continue
        manifests[path.name] = members
        unsafe = []
        for member in members:
            normalized = f"/{member.lower()}"
            public_demo = "/examples/public-demo/questions/" in normalized
            if not public_demo and any(part in normalized for part in FORBIDDEN_ARCHIVE_PARTS):
                unsafe.append(member)
        checks.append(
            Check(
                f"archive:{path.name}",
                "passed" if not unsafe else "failed",
                f"{len(members)} members; {len(unsafe)} forbidden",
            )
        )
    if not manifests:
        checks.append(Check("archive-inspection", "failed", "no archives to inspect"))
    return checks, manifests


def _smoke(root: Path, artifacts: Path, skip: bool) -> list[Check]:
    if skip:
        return [Check("installed-smoke", "failed", "skipped by request")]
    wheels = sorted(artifacts.glob("*.whl"))
    if len(wheels) != 1:
        return [Check("installed-smoke", "failed", "exactly one wheel is required")]
    with tempfile.TemporaryDirectory(prefix="qbank-smoke-") as temp:
        smoke_venv = Path(temp) / "smoke-venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(smoke_venv)
        python = _python(smoke_venv)
        install = _run(root, [str(python), "-m", "pip", "install", str(wheels[0])], timeout=900)
        if install.returncode != 0:
            return [Check("installed-smoke", "failed", _last_line(install))]
        commands = (
            [str(python), "-c", "import qbank; print(qbank.__version__)"],
            [str(python), "-m", "qbank", "--help"],
            [str(python), "-m", "qbank", "schema", "--format", "json"],
        )
        for command in commands:
            result = _run(root, command, timeout=120)
            if result.returncode != 0:
                return [Check("installed-smoke", "failed", _last_line(result))]
    return [Check("installed-smoke", "passed", "import, help, and schema succeeded")]


def _checksums(artifacts: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(artifacts.glob("*")):
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz")):
            values[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


def _release_notes(root: Path, version: str) -> str:
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(?ms)^##\s+{re.escape(version)}(?:\s+[^\n]*)?\n(?P<body>.*?)(?=^##\s+|\Z)"
    )
    match = pattern.search(changelog)
    body = (
        match.group("body").strip()
        if match
        else "Release details must be completed from CHANGELOG.md."
    )
    return f"# qbank {version}\n\n{body}\n\n## Artifacts\n\nWheel, source distribution, and SHA-256 checksums are attached.\n"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _report(decision: str, version: str, checks: list[Check]) -> str:
    lines = [
        f"# Release readiness for {version}",
        "",
        f"**Decision: {decision}**",
        "",
        "## Checks",
        "",
    ]
    lines.extend(
        f"- **{check.status.upper()}** `{check.name}` — {check.detail}" for check in checks
    )
    lines.extend(
        [
            "",
            "No tag, push, repository visibility change, or GitHub Release was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def prepare(root: Path, output: Path, skip_quality: bool, skip_build: bool) -> int:
    root = root.resolve()
    output = output.resolve()
    artifacts = output / "artifacts"
    output.mkdir(parents=True, exist_ok=True)
    name, version = _metadata(root)
    audit_decision, audit_check = _read_audit(root)
    status = _git(root, "status", "--porcelain")
    branch = _git(root, "branch", "--show-current")
    commit = _git(root, "rev-parse", "HEAD")
    tags = _git(root, "tag", "--points-at", "HEAD").splitlines()
    checks = [
        audit_check,
        Check(
            "git-worktree",
            "passed" if not status else "failed",
            "clean" if not status else "has uncommitted changes",
        ),
        Check("git-branch", "passed" if branch else "failed", branch or "detached or unavailable"),
        Check(
            "version", "passed" if re.fullmatch(r"\d+\.\d+\.\d+", version) else "failed", version
        ),
        *_check_readme(root),
        *_compatibility_checks(root, version),
    ]
    checks.extend(_run_quality_gates(root, skip_quality))
    checks.extend(_build(root, artifacts, skip_build))
    archive_checks, manifests = _inspect_archives(artifacts)
    checks.extend(archive_checks)
    checks.extend(_smoke(root, artifacts, skip_build))
    hashes = _checksums(artifacts)
    decision = (
        "GREEN" if checks and all(check.status == "passed" for check in checks) else "BLOCKED"
    )
    (output / "checksums.txt").write_text(
        "".join(f"{digest}  {filename}\n" for filename, digest in hashes.items()), encoding="utf-8"
    )
    (output / "release-notes.md").write_text(_release_notes(root, version), encoding="utf-8")
    plan = {
        "decision": decision,
        "project": name,
        "version": version,
        "tag": f"v{version}",
        "branch": branch,
        "commit": commit,
        "head_tags": tags,
        "oss_readiness": audit_decision,
        "remote_writes": False,
        "checks": [asdict(check) for check in checks],
        "artifacts": hashes,
        "archive_members": manifests,
        "next_step": "Obtain explicit user approval, then run $github-publish prepare."
        if decision == "GREEN"
        else "Resolve failed checks and rerun release preparation.",
    }
    _write_json(output / "release-plan.json", plan)
    (output / "release-readiness.md").write_text(
        _report(decision, version, checks), encoding="utf-8"
    )
    print(json.dumps({"decision": decision, "version": version, "output": str(output)}))
    return 0 if decision == "GREEN" else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-quality-gates", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "build" / "release"
    return prepare(root, output, args.skip_quality_gates, args.skip_build)


if __name__ == "__main__":
    sys.exit(main())
