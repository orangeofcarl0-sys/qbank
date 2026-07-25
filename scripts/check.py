"""Lightweight monorepo verification orchestrator."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps" / "studio"
IMPACT_FILE = ROOT / "scripts" / "change-impact.json"
SCOPES = {"core", "legacy", "sidecar", "studio", "build", "docs"}


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def cargo_check_command() -> list[str]:
    target = os.environ.get("QBANK_STUDIO_RUST_TARGET")
    if target is None and sys.platform == "win32":
        target = "x86_64-pc-windows-msvc"
    command = ["cargo"]
    command.extend(
        [
            "check",
            "--manifest-path",
            str(STUDIO / "src-tauri" / "Cargo.toml"),
        ]
    )
    if target:
        command.extend(["--target", target])
    return command


def import_linter_command() -> list[str]:
    executable = Path(sys.executable).with_name(
        "lint-imports.exe" if sys.platform == "win32" else "lint-imports"
    )
    return [str(executable)] if executable.exists() else ["lint-imports"]


def git_lines(arguments: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def changed_paths(since: str | None) -> set[str]:
    paths = git_lines(["diff", "--name-only", "--diff-filter=ACMR", "HEAD"])
    paths |= git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "HEAD"])
    paths |= git_lines(["ls-files", "--others", "--exclude-standard"])
    if since:
        paths |= git_lines(["diff", "--name-only", "--diff-filter=ACMR", f"{since}...HEAD"])
    return paths


def matches(path: str, patterns: list[str]) -> bool:
    candidate = PurePosixPath(path)
    return any(candidate.match(pattern) for pattern in patterns)


def load_impact() -> dict[str, Any]:
    return json.loads(IMPACT_FILE.read_text(encoding="utf-8"))


def infer_scopes(paths: set[str]) -> set[str]:
    mappings = load_impact()["scopes"]
    return {
        scope
        for scope, patterns in mappings.items()
        if any(matches(path, patterns) for path in paths)
    }


def python_targets(paths: set[str], scopes: set[str]) -> list[str]:
    candidates = sorted(path for path in paths if path.endswith(".py") and (ROOT / path).is_file())
    if candidates:
        return candidates
    targets: list[str] = []
    if "core" in scopes:
        targets.extend(["src/qbank", "tests/test_architecture_contracts.py"])
    if "legacy" in scopes:
        targets.append("src/qbank/legacy_qt")
    if "sidecar" in scopes:
        targets.extend(["src/qbank/studio_sidecar", "tests/studio_sidecar", "protocol/tests"])
    if "build" in scopes:
        targets.extend(["scripts/check.py", "scripts/build.py"])
    return targets


def run_fast(scopes: set[str], paths: set[str]) -> None:
    targets = python_targets(paths, scopes)
    if targets:
        run([sys.executable, "-m", "ruff", "check", *targets])
        run(
            [
                sys.executable,
                "-m",
                "pyright",
                *[target for target in targets if target.startswith("src/")],
            ]
        )
    if "core" in scopes:
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_architecture_contracts.py",
                "tests/test_architecture_refactor.py",
                "tests/test_cli.py",
            ]
        )
    if "legacy" in scopes:
        run([sys.executable, "-m", "pytest", "-q", "tests/test_desktop_entrypoints.py"])
    if "sidecar" in scopes:
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/studio_sidecar",
                "protocol/tests",
            ]
        )
    if "studio" in scopes:
        run(["npm", "run", "check"], cwd=STUDIO)
    if "build" in scopes:
        run([sys.executable, "-m", "pytest", "-q", "tests/test_unified_build.py"])
    if "docs" in scopes:
        run([sys.executable, "scripts/check_docs_sync.py"])


def run_integration(scopes: set[str]) -> None:
    if scopes & {"sidecar", "core", "build"}:
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/studio_sidecar",
                "protocol/tests",
                "tests/test_architecture_contracts.py",
            ]
        )
    if scopes & {"studio", "build"}:
        run(["npm", "run", "build"], cwd=STUDIO)
        run(
            [
                "npm",
                "run",
                "test:browser",
                "--",
                "tests/browser/monorepo-smoke.spec.ts",
            ],
            cwd=STUDIO,
        )
        run(cargo_check_command())


def run_release() -> None:
    run([sys.executable, "scripts/check_docs_sync.py"])
    run([sys.executable, "-m", "ruff", "format", "--check", "."])
    run([sys.executable, "-m", "ruff", "check", "."])
    run([sys.executable, "-m", "pyright"])
    run([sys.executable, "-m", "mypy", "src/qbank"])
    run(import_linter_command())
    run([sys.executable, "-m", "deptry", "."])
    run([sys.executable, "-m", "pytest", "--cov=qbank", "--cov-fail-under=90"])
    run(["npm", "run", "check"], cwd=STUDIO)
    run(["npm", "run", "test:browser"], cwd=STUDIO)
    run(
        [
            "cargo",
            "fmt",
            "--manifest-path",
            str(STUDIO / "src-tauri" / "Cargo.toml"),
            "--check",
        ]
    )
    run(
        [
            "cargo",
            "clippy",
            "--manifest-path",
            str(STUDIO / "src-tauri" / "Cargo.toml"),
            "--all-targets",
            "--all-features",
            "--",
            "-D",
            "warnings",
        ]
    )
    run([sys.executable, "-m", "pip", "check"])
    run([sys.executable, "-m", "pip_audit"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("level", choices=("fast", "integration", "release"))
    parser.add_argument("--since", help="also include changes since this Git revision")
    parser.add_argument("--scope", action="append", choices=sorted((*SCOPES, "all")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = changed_paths(args.since)
    requested = set(args.scope or ())
    scopes = SCOPES if "all" in requested else requested
    if not scopes:
        scopes = infer_scopes(paths)
    if not scopes:
        scopes = {"docs"}
        run([sys.executable, "-c", "import qbank; print(qbank.__version__)"])
    print(f"check level={args.level}; scopes={','.join(sorted(scopes))}")
    if args.level == "fast":
        run_fast(scopes, paths)
    elif args.level == "integration":
        run_integration(scopes)
    else:
        run_release()


if __name__ == "__main__":
    main()
