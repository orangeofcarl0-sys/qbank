"""Build qbank wheel and QBank Studio artifacts from one Git revision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import venv
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps" / "studio"
OUTPUT = ROOT / "build" / "unified"
PYTHON_VERSION = "0.3.0b1"
DISPLAY_VERSION = "0.3.0-beta.1"


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    environment: dict[str, str] | None = None,
) -> None:
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def output_of(command: list[str]) -> str:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def versions() -> dict[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((STUDIO / "package.json").read_text(encoding="utf-8"))
    protocol = json.loads((ROOT / "protocol/studio-protocol-v1.json").read_text(encoding="utf-8"))
    result = {
        "python": str(project["project"]["version"]),
        "display": str(package["version"]),
        "protocol": str(protocol["protocolVersion"]),
        "questionSchema": "1.0",
        "assetSchema": "1.0",
        "paperSchema": "1.0",
    }
    if result["python"] != PYTHON_VERSION or result["display"] != DISPLAY_VERSION:
        raise SystemExit(f"version mismatch: {result}")
    return result


def git_state(allow_dirty: bool) -> tuple[str, bool]:
    commit = output_of(["git", "rev-parse", "HEAD"])
    dirty = bool(output_of(["git", "status", "--porcelain"]))
    if dirty and not allow_dirty:
        raise SystemExit("refusing reproducible build from a dirty worktree; commit first")
    return commit, dirty


def ensure_output() -> Path:
    artifacts = OUTPUT / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def build_wheel(artifacts: Path) -> Path:
    for candidate in artifacts.glob("qbank-*.whl"):
        candidate.unlink()
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(artifacts),
        ]
    )
    return next(artifacts.glob(f"qbank-{PYTHON_VERSION}-*.whl"))


def venv_python(directory: Path) -> Path:
    python = directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(directory)
    return python


def build_sidecar(wheel: Path, target: str) -> Path:
    environment = OUTPUT / "sidecar-venv"
    python = venv_python(environment)
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--force-reinstall",
            str(wheel),
            "pyinstaller>=6.11,<7",
        ]
    )
    dist = OUTPUT / "sidecar-dist"
    work = OUTPUT / "sidecar-build"
    run(
        [
            str(python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "qbank-sidecar",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
            "--specpath",
            str(work),
            str(STUDIO / "scripts" / "sidecar-entry.py"),
        ]
    )
    source = dist / ("qbank-sidecar.exe" if sys.platform == "win32" else "qbank-sidecar")
    destination = STUDIO / "src-tauri" / "binaries" / f"qbank-sidecar-{target}.exe"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def ensure_node_dependencies() -> None:
    if not (STUDIO / "node_modules").is_dir():
        run(["npm", "ci"], cwd=STUDIO)


def release_directory(target: str) -> Path:
    return STUDIO / "src-tauri" / "target" / target / "release"


def default_target() -> str:
    configured = os.environ.get("QBANK_STUDIO_RUST_TARGET")
    if configured:
        return configured
    return "x86_64-pc-windows-msvc" if sys.platform == "win32" else ""


def rust_environment(target: str) -> dict[str, str]:
    environment = os.environ.copy()
    if target == "x86_64-pc-windows-gnu":
        environment["RUSTUP_TOOLCHAIN"] = "stable-x86_64-pc-windows-gnu"
    return environment


def build_studio(wheel: Path, artifacts: Path, target: str) -> tuple[Path, Path]:
    build_sidecar(wheel, target)
    ensure_node_dependencies()
    run(["npm", "run", "check"], cwd=STUDIO)
    run(
        ["npx", "tauri", "build", "--ci", "--target", target, "--bundles", "nsis"],
        cwd=STUDIO,
        environment=rust_environment(target),
    )
    release = release_directory(target)
    main = release / "qbank-studio.exe"
    sidecar = release / "qbank-sidecar.exe"
    loader = release / "WebView2Loader.dll"
    installer = next((release / "bundle" / "nsis").glob("*-setup.exe"))
    installer_output = artifacts / f"QBank-Studio-{DISPLAY_VERSION}-x64-setup.exe"
    shutil.copy2(installer, installer_output)

    portable_root = OUTPUT / f"QBank-Studio-{DISPLAY_VERSION}-portable"
    if portable_root.exists():
        shutil.rmtree(portable_root)
    portable_root.mkdir(parents=True)
    for source, name in (
        (main, "qbank-studio.exe"),
        (sidecar, "qbank-sidecar.exe"),
        (loader, "WebView2Loader.dll"),
        (STUDIO / "scripts" / "portable-README.txt", "README.txt"),
    ):
        shutil.copy2(source, portable_root / name)
    archive = artifacts / f"QBank-Studio-{DISPLAY_VERSION}-portable-x64.zip"
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for source in sorted(portable_root.iterdir()):
            bundle.write(source, f"{portable_root.name}/{source.name}")
    return installer_output, archive


def lock_hashes() -> dict[str, str]:
    paths = (
        "requirements-dev.lock",
        "apps/studio/package-lock.json",
        "apps/studio/src-tauri/Cargo.lock",
    )
    return {path: sha256(ROOT / path) for path in paths}


def write_manifest(
    artifacts: list[Path],
    *,
    commit: str,
    dirty: bool,
    target: str,
) -> None:
    data: dict[str, Any] = {
        "gitCommit": commit,
        "dirty": dirty,
        "target": target,
        "versions": versions(),
        "locks": lock_hashes(),
        "artifacts": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in artifacts
        ],
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "release-manifest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "checksums.txt").write_text(
        "".join(f"{item['sha256']}  {item['name']}\n" for item in data["artifacts"]),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("wheel", "studio", "all"))
    parser.add_argument("--target", default=default_target())
    parser.add_argument("--allow-dirty", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    versions()
    commit, dirty = git_state(args.allow_dirty)
    artifacts_dir = ensure_output()
    wheel = build_wheel(artifacts_dir)
    artifacts = [wheel]
    if args.kind in {"studio", "all"}:
        artifacts.extend(build_studio(wheel, artifacts_dir, args.target))
    write_manifest(artifacts, commit=commit, dirty=dirty, target=args.target)
    print(f"built {len(artifacts)} artifact(s) from {commit}")


if __name__ == "__main__":
    main()
