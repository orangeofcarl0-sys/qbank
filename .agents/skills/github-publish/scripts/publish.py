#!/usr/bin/env python3
"""Prepare or execute a confirmation-gated GitHub publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PublishRequest:
    root: Path
    repository: str
    tag: str
    visibility: str
    create_repository: bool


def _run(root: Path, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _git(root: Path, *args: str) -> tuple[bool, str]:
    result = _run(root, ["git", *args], timeout=60)
    return result.returncode == 0, result.stdout.strip()


def _load_plan(root: Path) -> dict[str, Any]:
    path = root / "build" / "release" / "release-plan.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _prepared_attachments(root: Path, plan: dict[str, Any]) -> dict[str, str]:
    artifacts = dict(plan.get("artifacts", {}))
    checksum = root / "build" / "release" / "checksums.txt"
    if checksum.is_file():
        artifacts[checksum.name] = hashlib.sha256(checksum.read_bytes()).hexdigest()
    return artifacts


def _preflight(request: PublishRequest) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    plan = _load_plan(request.root)
    if plan.get("decision") != "GREEN":
        blockers.append("release-preparation is not GREEN")
    if plan.get("oss_readiness") != "GREEN":
        blockers.append("oss-readiness is not GREEN")
    clean, status = _git(request.root, "status", "--porcelain")
    if not clean or status:
        blockers.append("worktree is not clean")
    ok, branch = _git(request.root, "branch", "--show-current")
    if not ok or not branch:
        blockers.append("current branch is unavailable")
    ok, commit = _git(request.root, "rev-parse", "HEAD")
    if not ok:
        blockers.append("current commit is unavailable")
    _, existing_tag = _git(request.root, "tag", "--list", request.tag)
    if existing_tag:
        blockers.append(f"tag already exists locally: {request.tag}")
    if plan.get("tag") != request.tag:
        blockers.append("requested tag does not match the prepared release")
    if request.visibility != "public":
        blockers.append("open-source publication visibility must be public")
    artifacts = _prepared_attachments(request.root, plan)
    if not artifacts:
        blockers.append("prepared artifacts are missing")
    details = {
        "repository": request.repository,
        "visibility": request.visibility,
        "create_repository": request.create_repository,
        "branch": branch,
        "commit": commit,
        "tag": request.tag,
        "release_title": str(plan.get("release_title", f"QBank {request.tag.removeprefix('v')}")),
        "prerelease": bool(plan.get("prerelease", False)),
        "attachments": artifacts,
        "operations": [
            "create public repository" if request.create_repository else "use target repository",
            "make target repository public if necessary",
            "atomically push current branch and new tag",
            "create GitHub Release",
            "upload wheel, sdist, Studio artifacts, checksums, and release manifest",
            "download and verify published attachments",
        ],
        "remote_writes": False,
        "ready": not blockers,
        "blockers": blockers,
    }
    return blockers, details


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def prepare(request: PublishRequest) -> int:
    blockers, details = _preflight(request)
    path = request.root / "build" / "release" / "publish-plan.json"
    _write_json(path, details)
    print(json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True))
    if not blockers:
        create_flag = " --create-repository" if request.create_repository else ""
        print(
            "Approval-gated next command:\n"
            f"python .agents/skills/github-publish/scripts/publish.py commit --root . "
            f"--repository {request.repository} --tag {request.tag} --visibility public"
            f"{create_flag} --confirm-publish"
        )
    return 0 if not blockers else 3


def _gh(root: Path, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gh")
    if executable is None:
        return subprocess.CompletedProcess(args, 127, "", "GitHub CLI is not installed")
    return _run(root, [executable, *args], timeout=timeout)


def _ensure_repository(request: PublishRequest) -> tuple[bool, str]:
    result = _gh(request.root, ["repo", "view", request.repository, "--json", "visibility,url"])
    if result.returncode != 0:
        if not request.create_repository:
            return False, "target repository does not exist or is inaccessible"
        created = _gh(
            request.root,
            ["repo", "create", request.repository, "--public", "--source", str(request.root)],
        )
        return created.returncode == 0, created.stderr.strip() or created.stdout.strip()
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, "could not read target repository visibility"
    if str(metadata.get("visibility", "")).upper() == "PUBLIC":
        return True, str(metadata.get("url", ""))
    edited = _gh(
        request.root,
        [
            "repo",
            "edit",
            request.repository,
            "--visibility",
            "public",
            "--accept-visibility-change-consequences",
        ],
    )
    return edited.returncode == 0, edited.stderr.strip() or edited.stdout.strip()


def _artifact_paths(root: Path) -> list[Path]:
    artifacts = root / "build" / "release" / "artifacts"
    paths = sorted(path for path in artifacts.glob("*") if path.is_file())
    checksum = root / "build" / "release" / "checksums.txt"
    if checksum.is_file():
        paths.append(checksum)
    return paths


def _verify_downloads(downloaded: Path, expected: dict[str, str]) -> tuple[bool, dict[str, str]]:
    actual: dict[str, str] = {}
    for name, digest in expected.items():
        path = downloaded / name
        if not path.is_file():
            return False, actual
        actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual[name] != digest:
            return False, actual
    return True, actual


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _smoke_downloaded_wheel(root: Path, downloaded: Path) -> tuple[bool, str]:
    wheels = sorted(downloaded.glob("*.whl"))
    if len(wheels) != 1:
        return False, "exactly one downloaded wheel is required"
    smoke_venv = downloaded / "smoke-venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(smoke_venv)
    python = _venv_python(smoke_venv)
    installed = _run(root, [str(python), "-m", "pip", "install", str(wheels[0])], timeout=900)
    if installed.returncode != 0:
        return False, "downloaded wheel installation failed"
    tested = _run(root, [str(python), "-m", "qbank", "--help"], timeout=120)
    return tested.returncode == 0, "installed qbank --help smoke test"


def _validated_commit_details(
    request: PublishRequest, confirmed: bool
) -> tuple[dict[str, Any] | None, int]:
    if not confirmed:
        print(
            "Refusing publication: --confirm-publish is required after explicit user approval.",
            file=sys.stderr,
        )
        return None, 5
    blockers, details = _preflight(request)
    plan_path = request.root / "build" / "release" / "publish-plan.json"
    if not plan_path.is_file():
        print(
            "Refusing publication: run the prepare phase and show its plan first.", file=sys.stderr
        )
        return None, 5
    try:
        prepared = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("Refusing publication: the prepared plan is invalid.", file=sys.stderr)
        return None, 5
    comparable = ("repository", "visibility", "create_repository", "tag", "commit")
    if any(prepared.get(key) != details.get(key) for key in comparable):
        blockers.append("prepared plan does not match this commit request")
    if blockers:
        print("Refusing publication: " + "; ".join(blockers), file=sys.stderr)
        return None, 5
    if shutil.which("gh") is None:
        print("Refusing publication: GitHub CLI is unavailable.", file=sys.stderr)
        return None, 7
    return details, 0


def _prepare_remote_target(request: PublishRequest) -> tuple[str | None, int]:
    remote_tag = _run(
        request.root,
        [
            "git",
            "ls-remote",
            "--tags",
            f"https://github.com/{request.repository}.git",
            f"refs/tags/{request.tag}",
        ],
        timeout=60,
    )
    if remote_tag.returncode != 0 or remote_tag.stdout.strip():
        print(
            "Refusing publication: remote tag check failed or the tag already exists.",
            file=sys.stderr,
        )
        return None, 5
    repo_ok, repo_detail = _ensure_repository(request)
    if not repo_ok:
        print(f"Repository preparation failed: {repo_detail}", file=sys.stderr)
        return None, 6
    return repo_detail, 0


def _push_refs(request: PublishRequest, details: dict[str, Any]) -> int:
    tagged = _run(request.root, ["git", "tag", "-a", request.tag, "-m", details["release_title"]])
    if tagged.returncode != 0:
        print(tagged.stderr.strip(), file=sys.stderr)
        return 6
    pushed = _run(
        request.root,
        [
            "git",
            "push",
            "--atomic",
            f"https://github.com/{request.repository}.git",
            details["branch"],
            f"refs/tags/{request.tag}",
        ],
        timeout=300,
    )
    if pushed.returncode != 0:
        print("Atomic push failed; the local tag was retained for inspection.", file=sys.stderr)
        return 6
    return 0


def _create_release(request: PublishRequest, details: dict[str, Any]) -> int:
    notes = request.root / "build" / "release" / "release-notes.md"
    release_args = [
        "release",
        "create",
        request.tag,
        "--repo",
        request.repository,
        "--title",
        details["release_title"],
        "--notes-file",
        str(notes),
    ]
    if details.get("prerelease"):
        release_args.extend(["--prerelease", "--latest=false"])
    release_args.extend(str(path) for path in _artifact_paths(request.root))
    released = _gh(request.root, release_args, timeout=600)
    if released.returncode != 0:
        print("Code and tag were pushed, but GitHub Release creation failed.", file=sys.stderr)
        return 6
    return 0


def _download_and_verify(
    request: PublishRequest, details: dict[str, Any]
) -> tuple[dict[str, str] | None, int]:
    with tempfile.TemporaryDirectory(prefix="qbank-release-verify-") as temp:
        downloaded = Path(temp)
        fetched = _gh(
            request.root,
            [
                "release",
                "download",
                request.tag,
                "--repo",
                request.repository,
                "--dir",
                str(downloaded),
            ],
            timeout=600,
        )
        if fetched.returncode != 0:
            print("Release created, but attachment verification download failed.", file=sys.stderr)
            return None, 6
        verified, actual = _verify_downloads(downloaded, details["attachments"])
        smoke_ok, smoke_detail = _smoke_downloaded_wheel(request.root, downloaded)
    if not verified:
        print("Release created, but downloaded attachment hashes did not match.", file=sys.stderr)
        return None, 6
    if not smoke_ok:
        print(f"Release created, but {smoke_detail} failed.", file=sys.stderr)
        return None, 6
    return actual, 0


def _release_url(request: PublishRequest) -> str:
    view = _gh(
        request.root,
        ["release", "view", request.tag, "--repo", request.repository, "--json", "url"],
    )
    if view.returncode != 0:
        return ""
    try:
        return str(json.loads(view.stdout).get("url", ""))
    except json.JSONDecodeError:
        return ""


def commit(request: PublishRequest, confirmed: bool) -> int:
    details, exit_code = _validated_commit_details(request, confirmed)
    if details is None:
        return exit_code
    repo_detail, exit_code = _prepare_remote_target(request)
    if repo_detail is None:
        return exit_code
    exit_code = _push_refs(request, details)
    if exit_code:
        return exit_code
    exit_code = _create_release(request, details)
    if exit_code:
        return exit_code
    actual, exit_code = _download_and_verify(request, details)
    if actual is None:
        return exit_code
    record = {
        **details,
        "remote_writes": True,
        "release_url": _release_url(request),
        "repository_detail": repo_detail,
        "verified_attachment_hashes": actual,
    }
    _write_json(request.root / "build" / "release" / "publication.json", record)
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("prepare", "commit"):
        command = subparsers.add_parser(action)
        command.add_argument("--root", type=Path, default=Path.cwd())
        command.add_argument("--repository", required=True)
        command.add_argument("--tag", required=True)
        command.add_argument("--visibility", choices=("public",), required=True)
        command.add_argument("--create-repository", action="store_true")
        if action == "commit":
            command.add_argument("--confirm-publish", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    request = PublishRequest(
        root=args.root.resolve(),
        repository=args.repository,
        tag=args.tag,
        visibility=args.visibility,
        create_repository=args.create_repository,
    )
    if args.action == "prepare":
        return prepare(request)
    return commit(request, args.confirm_publish)


if __name__ == "__main__":
    sys.exit(main())
