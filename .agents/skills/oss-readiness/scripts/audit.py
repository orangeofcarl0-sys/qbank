#!/usr/bin/env python3
"""Generate a deterministic, redacted open-source readiness audit."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".import_linter_cache",
    "node_modules",
}
TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".rst",
    ".svg",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}
MEDIA_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".pdf", ".png", ".svg", ".webp"}
FONT_EXTENSIONS = {".eot", ".otf", ".ttf", ".woff", ".woff2"}
ARCHIVE_EXTENSIONS = {".tar", ".whl", ".zip"}


@dataclass(frozen=True)
class Finding:
    category: str
    severity: str
    source: str
    path: str
    line: int | None
    message: str
    evidence_hash: str
    remediation: str


@dataclass(frozen=True)
class ToolResult:
    name: str
    available: bool
    status: str
    detail: str


def _run(root: Path, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _which(name: str) -> str | None:
    sibling = Path(sys.executable).parent / (f"{name}.exe" if os.name == "nt" else name)
    return str(sibling) if sibling.is_file() else shutil.which(name)


def _fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]


def _finding(  # noqa: PLR0913 - explicit fields prevent unsafe evidence/message mix-ups
    category: str,
    severity: str,
    source: str,
    path: str,
    line: int | None,
    message: str,
    evidence: str,
    remediation: str,
) -> Finding:
    return Finding(
        category, severity, source, path, line, message, _fingerprint(evidence), remediation
    )


def _git_files(root: Path, args: list[str]) -> list[str]:
    result = _run(root, ["git", *args])
    if result.returncode != 0:
        return []
    return sorted(item for item in result.stdout.split("\0") if item)


def _walk_files(root: Path, output: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirs, names in os.walk(root):
        current_path = Path(current)
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in SKIP_DIRS
            and name.lower() != "site-packages"
            and not (current_path / name / "pyvenv.cfg").is_file()
            and (current_path / name).resolve() != output.resolve()
        )
        for name in sorted(names):
            path = current_path / name
            if output.resolve() in path.resolve().parents:
                continue
            files.append(path)
    return files


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > 5 * 1024 * 1024:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:4096] and path.suffix.lower() not in TEXT_EXTENSIONS:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace") if path.suffix.lower() in TEXT_EXTENSIONS else None


def _scan_text(text: str, source: str, path: str) -> list[Finding]:
    rules = (
        (
            "secret",
            "CRITICAL",
            re.compile(
                r"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
                r"sk-[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
            ),
            "Potential credential or private key",
            "Revoke if real, remove from the current tree and rewrite affected Git history.",
        ),
        (
            "secret",
            "CRITICAL",
            re.compile(
                r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*"
                r"['\"]?[A-Za-z0-9_./+=-]{12,}"
            ),
            "Potential assigned secret",
            "Verify and revoke if real; replace with a documented environment variable.",
        ),
        (
            "absolute_path",
            "MEDIUM",
            re.compile(
                r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/](?:Users|project|Program Files|tools)"
                r"[\\/][^\s'\"<>]+|\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+"
                r"(?:\\[A-Za-z0-9$._-][^\s\\]*)+)"
            ),
            "Machine-specific Windows or UNC path",
            "Replace public documentation/configuration with a relative path or placeholder.",
        ),
        (
            "private_address",
            "MEDIUM",
            re.compile(
                r"(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\d)"
            ),
            "Private network address",
            "Remove or replace the private endpoint with a non-routable example.",
        ),
        (
            "private_repository",
            "HIGH",
            re.compile(r"(?i)(?:ssh://git" + r"@|git" + r"@)[^\s:]+[:/][^\s]+\.git"),
            "SSH repository address may identify a private remote",
            "Use a public HTTPS URL only after the target repository is approved.",
        ),
        (
            "email",
            "MEDIUM",
            re.compile(
                r"(?i)\b[A-Z0-9._%+-]+@(?!example\.(?:com|org)|users\.noreply\.github\.com)[A-Z0-9.-]+\.[A-Z]{2,}\b"
            ),
            "Email address may be personal",
            "Confirm publication is intentional or replace with an example address.",
        ),
    )
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for category, severity, pattern, message, remediation in rules:
            for match in pattern.finditer(line):
                findings.append(
                    _finding(
                        category,
                        severity,
                        source,
                        path,
                        line_number,
                        message,
                        match.group(0),
                        remediation,
                    )
                )
    return findings


def _scan_tree(root: Path, output: Path) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    seen: list[str] = []
    if (root / "build").is_dir():
        findings.append(
            _finding(
                "local_artifact",
                "MEDIUM",
                "worktree",
                "build/",
                None,
                "Ignored build output is present and was checked as a non-distributable surface",
                "build-directory-present",
                "Keep build output ignored and verify archive manifests before publication.",
            )
        )
    for item in _walk_files(root, output):
        relative = item.relative_to(root).as_posix()
        seen.append(relative)
        lowered = relative.lower()
        synthetic_demo = lowered.startswith("examples/public-demo/")
        if not synthetic_demo and re.search(
            r"(?:^|/)(?:integration-pilot|questions)(?:/|$)", lowered
        ):
            findings.append(
                _finding(
                    "private_question_data",
                    "HIGH",
                    "worktree",
                    relative,
                    None,
                    "Question-bank or integration-pilot data is present",
                    relative,
                    "Exclude real user/exam data; publish only the synthetic example bank.",
                )
            )
        if re.search(r"(?:2005\D*2022|(?:19|20)\d{2}.*(?:answer|答案|试题|exam))", lowered):
            findings.append(
                _finding(
                    "exam_material",
                    "HIGH",
                    "worktree",
                    relative,
                    None,
                    "Dated exam or answer material may be copyrighted",
                    relative,
                    "Remove from all distributable surfaces unless redistribution is documented.",
                )
            )
        if item.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".log"}:
            findings.append(
                _finding(
                    "local_artifact",
                    "MEDIUM",
                    "worktree",
                    relative,
                    None,
                    "Local database or log is present",
                    relative,
                    "Keep local indexes and logs ignored and outside release archives.",
                )
            )
        text = _read_text(item)
        if text is not None:
            findings.extend(_scan_text(text, "worktree", relative))
        elif item.suffix.lower() in MEDIA_EXTENSIONS and _has_metadata(item):
            findings.append(
                _finding(
                    "media_metadata",
                    "MEDIUM",
                    "worktree",
                    relative,
                    None,
                    "Media file contains an EXIF or textual metadata container",
                    relative,
                    "Inspect and strip personal metadata while preserving license attribution.",
                )
            )
    return findings, sorted(seen)


def _has_metadata(path: Path) -> bool:
    try:
        data = path.read_bytes()[:2_000_000]
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return b"Exif\x00\x00" in data
    if suffix == ".png":
        return any(chunk in data for chunk in (b"tEXt", b"iTXt", b"zTXt", b"eXIf"))
    return False


def _scan_history(root: Path) -> tuple[list[Finding], bool]:
    result = _run(
        root,
        ["git", "log", "--all", "--full-history", "--no-ext-diff", "--text", "-p"],
        timeout=300,
    )
    if result.returncode != 0:
        return [], False
    scanned = _scan_text(result.stdout, "git-history", "<history>")
    findings = [
        Finding(
            item.category,
            item.severity,
            item.source,
            item.path,
            None,
            item.message,
            item.evidence_hash,
            item.remediation,
        )
        for item in scanned
    ]
    return findings, True


def _scan_git_identities(root: Path) -> list[Finding]:
    result = _run(root, ["git", "log", "--all", "--format=%an%x00%ae"], timeout=120)
    if result.returncode != 0:
        return []
    findings: list[Finding] = []
    for record in sorted(set(result.stdout.splitlines())):
        author, separator, email = record.partition("\0")
        if not separator or not author.strip():
            continue
        findings.append(
            _finding(
                "git_identity",
                "MEDIUM",
                "git-history",
                "<history>",
                None,
                "Git history contains an author name and email identity",
                f"{author.strip()}\0{email.strip()}",
                "Confirm the Git author identity is acceptable for permanent public history.",
            )
        )
    return findings


def _tool_version(root: Path, name: str) -> ToolResult:
    executable = _which(name)
    if executable is None:
        return ToolResult(name, False, "warning", "not installed; local fallback used")
    result = _run(root, [executable, "--version"], timeout=15)
    detail = (result.stdout or result.stderr).strip().splitlines()
    return ToolResult(name, True, "available", detail[0][:200] if detail else "available")


def _run_secret_tool(root: Path, name: str) -> tuple[ToolResult, Finding | None]:
    executable = _which(name)
    if executable is None:
        return _tool_version(root, name), None
    if name == "gitleaks":
        args = [executable, "git", str(root), "--redact", "--no-banner", "--report-format", "json"]
    else:
        args = [executable, "git", f"file://{root.as_posix()}", "--json", "--no-update"]
    try:
        result = _run(root, args, timeout=300)
    except subprocess.TimeoutExpired:
        return ToolResult(name, True, "warning", "timed out; local fallback used"), None
    if result.returncode == 0:
        return ToolResult(name, True, "passed", "completed without findings"), None
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    finding = _finding(
        "external_secret_scan",
        "CRITICAL",
        name,
        "<repository>",
        None,
        f"{name} reported potential secrets ({len(lines) or 'unknown'} records; raw values omitted)",
        f"{name}:{len(lines)}:{result.returncode}",
        "Review the scanner locally, revoke confirmed secrets, and rewrite affected history.",
    )
    return ToolResult(
        name, True, "findings", "potential secrets reported; details redacted"
    ), finding


def _run_analysis_tool(root: Path, name: str) -> tuple[ToolResult, Finding | None]:
    executable = _which(name)
    if executable is None:
        return _tool_version(root, name), None
    commands = {
        "pip-audit": [executable, "--format", "json"],
        "deptry": [executable, "."],
        "reuse": [executable, "lint"],
    }
    categories = {
        "pip-audit": ("dependency_vulnerability", "HIGH"),
        "deptry": ("dependency_hygiene", "MEDIUM"),
        "reuse": ("license_compliance", "HIGH"),
    }
    try:
        result = _run(root, commands[name], timeout=300)
    except subprocess.TimeoutExpired:
        return ToolResult(name, True, "warning", "timed out; local fallback used"), None
    if result.returncode == 0:
        return ToolResult(name, True, "passed", "analysis completed without findings"), None
    category, severity = categories[name]
    record_count = len([line for line in result.stdout.splitlines() if line.strip()])
    finding = _finding(
        category,
        severity,
        name,
        "<repository>",
        None,
        f"{name} reported issues (raw output omitted)",
        f"{name}:{result.returncode}:{record_count}",
        f"Run {name} locally, review its output, and resolve or document every issue.",
    )
    return ToolResult(
        name, True, "findings", "analysis reported issues; raw output omitted"
    ), finding


def _declared_license(metadata: importlib.metadata.PackageMetadata) -> str:
    declared = metadata.get("License-Expression") or metadata.get("License")
    if declared and declared.strip() not in {"", "UNKNOWN"}:
        return declared.strip()
    classifiers = metadata.get_all("Classifier") or []
    names = sorted(
        {
            classifier.split(" :: ")[-1]
            for classifier in classifiers
            if classifier.startswith("License ::")
        }
    )
    return "; ".join(names) if names else "UNKNOWN"


def _dependency_licenses(root: Path) -> dict[str, Any]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject.get("project", {}).get("dependencies", [])
    records: list[dict[str, str]] = []
    for requirement in dependencies:
        name = re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0].strip()
        try:
            metadata = importlib.metadata.metadata(name)
            license_name = _declared_license(metadata)
            version = metadata.get("Version", "UNKNOWN")
        except importlib.metadata.PackageNotFoundError:
            license_name, version = "UNKNOWN", "not-installed"
        records.append({"name": name, "version": version, "license": license_name})
    return {
        "project_license_file": (root / "LICENSE").is_file(),
        "project_license_expression": pyproject.get("project", {}).get("license"),
        "gitignore_present": (root / ".gitignore").is_file(),
        "manifest_present": (root / "MANIFEST.in").is_file(),
        "build_backend": pyproject.get("build-system", {}).get("build-backend"),
        "dependencies": records,
    }


def _license_findings(
    root: Path, all_files: Iterable[str], report: dict[str, Any]
) -> list[Finding]:
    findings: list[Finding] = []
    if not report["project_license_file"]:
        findings.append(
            _finding(
                "project_license",
                "HIGH",
                "metadata",
                "LICENSE",
                None,
                "Project license file is missing",
                "missing-license",
                "Add an approved project license before publication.",
            )
        )
    if not report["manifest_present"]:
        findings.append(
            _finding(
                "source_manifest",
                "LOW",
                "metadata",
                "MANIFEST.in",
                None,
                "No MANIFEST.in is present; backend defaults must be verified from the sdist",
                "missing-manifest",
                "Inspect the built sdist manifest and add MANIFEST.in only if backend rules are insufficient.",
            )
        )
    for dependency in report["dependencies"]:
        if dependency["license"] == "UNKNOWN":
            findings.append(
                _finding(
                    "dependency_license",
                    "MEDIUM",
                    "metadata",
                    "pyproject.toml",
                    None,
                    f"Dependency license is unknown for {dependency['name']}",
                    dependency["name"],
                    "Confirm the dependency license before publication.",
                )
            )
    for filename in all_files:
        suffix = Path(filename).suffix.lower()
        if suffix not in FONT_EXTENSIONS | MEDIA_EXTENSIONS:
            continue
        self_authored = filename.startswith("examples/public-demo/") or filename in {
            "examples/interference.svg",
            "src/qbank/resources/init/assets/images/interference.svg",
        }
        parent = root / Path(filename).parent
        relevant_parents = [
            candidate
            for candidate in (parent, *parent.parents)
            if candidate != root and root in candidate.parents
        ]
        notice = any(
            (candidate / notice_name).is_file()
            for candidate in relevant_parents
            for notice_name in ("LICENSE", "THIRD_PARTY_NOTICES.md")
        )
        if not self_authored and not notice:
            findings.append(
                _finding(
                    "asset_license",
                    "HIGH" if suffix in FONT_EXTENSIONS else "MEDIUM",
                    "worktree",
                    filename,
                    None,
                    "Redistribution basis is not declared near this asset",
                    filename,
                    "Add attribution/license evidence or replace with a self-authored asset.",
                )
            )
    return findings


def _gitignore_findings(root: Path) -> list[Finding]:
    path = root / ".gitignore"
    if not path.is_file():
        return [
            _finding(
                "gitignore",
                "HIGH",
                "metadata",
                ".gitignore",
                None,
                "The repository has no ignore policy",
                "missing-gitignore",
                "Add rules for build output, local state, caches, logs, and databases.",
            )
        ]
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    required = {
        "build output": "build/",
        "local qbank state": ".qbank/",
        "logs": "*.log",
        "SQLite databases": "*.sqlite",
        "virtual environments": ".venv/",
    }
    missing = [label for label, pattern in required.items() if pattern not in text]
    if not missing:
        return []
    return [
        _finding(
            "gitignore",
            "MEDIUM",
            "metadata",
            ".gitignore",
            None,
            "Ignore policy lacks: " + ", ".join(missing),
            "|".join(missing),
            "Add narrow ignore rules and confirm no matching files are already tracked.",
        )
    ]


def _archive_members(root: Path) -> list[str]:
    members: set[str] = set()
    for path in sorted((root / "build" / "release" / "artifacts").glob("*")):
        if path.suffix.lower() not in ARCHIVE_EXTENSIONS and not path.name.endswith(".tar.gz"):
            continue
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as archive:
                    members.update(f"{path.name}:{name}" for name in archive.namelist())
            else:
                with tarfile.open(path) as archive:
                    members.update(f"{path.name}:{name}" for name in archive.getnames())
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile):
            members.add(f"{path.name}:<unreadable>")
    return sorted(members)


def _planned_distributable(tracked: Iterable[str]) -> list[str]:
    allowed_roots = ("src/qbank/",)
    allowed_files = {"LICENSE", "README.md", "pyproject.toml"}
    return sorted(
        path for path in tracked if path in allowed_files or path.startswith(allowed_roots)
    )


def _deduplicate(findings: Iterable[Finding]) -> list[Finding]:
    unique = {tuple(asdict(item).values()): item for item in findings}
    return sorted(
        unique.values(),
        key=lambda item: (
            SEVERITY_ORDER[item.severity],
            item.path,
            item.line or 0,
            item.category,
            item.evidence_hash,
        ),
    )


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _render_report(findings: list[Finding], tools: list[ToolResult], history_ok: bool) -> str:
    counts = {name: sum(item.severity == name for item in findings) for name in SEVERITY_ORDER}
    blocking = counts["CRITICAL"] + counts["HIGH"]
    decision = "GREEN" if blocking == 0 and history_ok else "BLOCKED"
    lines = [
        "# Open-source readiness",
        "",
        f"**Decision: {decision}**",
        "",
        f"Findings: {counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low.",
        f"Full Git history scanned: {'yes' if history_ok else 'no'}.",
        "",
        "## Tool coverage",
        "",
    ]
    lines.extend(f"- {tool.name}: {tool.status} — {tool.detail}" for tool in tools)
    lines.extend(["", "## Findings", ""])
    if not findings:
        lines.append("No findings.")
    for item in findings:
        location = f"{item.path}:{item.line}" if item.line else item.path
        lines.append(
            f"- **{item.severity} {item.category}** — `{location}` — {item.message}. {item.remediation}"
        )
    lines.extend(["", "Reports contain fingerprints, not matched secret values.", ""])
    return "\n".join(lines)


def audit(root: Path, output: Path, skip_external: bool) -> int:
    root = root.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    tracked = _git_files(root, ["ls-files", "-z"])
    untracked = _git_files(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    tree_findings, all_files = _scan_tree(root, output)
    history_findings, history_ok = _scan_history(root)
    tools: list[ToolResult] = []
    external_findings: list[Finding] = []
    for name in ("gitleaks", "trufflehog"):
        if skip_external:
            tools.append(
                ToolResult(
                    name,
                    bool(_which(name)),
                    "skipped",
                    "explicitly skipped; local fallback used",
                )
            )
        else:
            result, finding = _run_secret_tool(root, name)
            tools.append(result)
            if finding:
                external_findings.append(finding)
    for name in ("pip-audit", "deptry", "reuse"):
        if skip_external:
            tools.append(
                ToolResult(
                    name,
                    bool(_which(name)),
                    "skipped",
                    "explicitly skipped; local fallback used",
                )
            )
        else:
            result, finding = _run_analysis_tool(root, name)
            tools.append(result)
            if finding:
                external_findings.append(finding)
    license_report = _dependency_licenses(root)
    license_findings = _license_findings(root, all_files, license_report)
    findings = _deduplicate(
        [
            *tree_findings,
            *history_findings,
            *_scan_git_identities(root),
            *external_findings,
            *license_findings,
            *_gitignore_findings(root),
        ]
    )
    counts = {name: sum(item.severity == name for item in findings) for name in SEVERITY_ORDER}
    decision = "GREEN" if counts["CRITICAL"] + counts["HIGH"] == 0 and history_ok else "BLOCKED"
    (output / "tracked-files.txt").write_text("\n".join(tracked) + "\n", encoding="utf-8")
    distributable = _planned_distributable(tracked)
    archive_members = _archive_members(root)
    (output / "distributable-files.txt").write_text(
        "\n".join([*distributable, *archive_members]) + "\n", encoding="utf-8"
    )
    _write_json(
        output / "findings.json",
        {
            "decision": decision,
            "counts": counts,
            "findings": [asdict(item) for item in findings],
            "untracked_files": untracked,
        },
    )
    _write_json(output / "license-report.json", license_report)
    _write_json(
        output / "secret-scan-report.json",
        {
            "history_scanned": history_ok,
            "redacted": True,
            "tools": [asdict(tool) for tool in tools],
            "secret_findings": [asdict(item) for item in findings if "secret" in item.category],
        },
    )
    (output / "readiness-report.md").write_text(
        _render_report(findings, tools, history_ok), encoding="utf-8"
    )
    print(json.dumps({"decision": decision, "findings": len(findings), "output": str(output)}))
    return 0 if decision == "GREEN" else 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-external", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "build" / "oss-audit"
    return audit(root, output, args.skip_external)


if __name__ == "__main__":
    sys.exit(main())
