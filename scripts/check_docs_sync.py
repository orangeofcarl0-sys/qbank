#!/usr/bin/env python3
"""Deterministic documentation and public-capability synchronization gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from typer.main import get_command  # noqa: E402

from qbank.cli import app  # noqa: E402
from qbank.codex_manifest import (  # noqa: E402
    INTEGRATION_CAPABILITIES,
    REQUIRED_COMMANDS,
    SKILL_FILES,
)

PUBLIC_FILES = (
    "README.md",
    "README.en.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/maintenance-policy.md",
    "docs/README.md",
    "docs/localization.md",
    "docs/feature-lifecycle.md",
    "docs/documentation-map.md",
    "docs/compatibility-policy.md",
    "docs/installation.md",
    "docs/cli-reference.md",
    "docs/zh-CN/mcp-guide.md",
    "docs/en/mcp-guide.md",
    "docs/zh-CN/roadmap.md",
    "docs/en/roadmap.md",
    "docs/features/README.md",
    "docs/features/_template.md",
    "docs/features/capability-matrix.md",
    "docs/features/bilingual-documentation.md",
    "docs/features/unified-studio-monorepo.md",
    "docs/adr/0006-unified-studio-monorepo.md",
    "docs/monorepo-development.md",
    "protocol/README.md",
    "protocol/studio-protocol-v1.json",
)
LOCALIZED_DOCUMENTS = (
    "README.md",
    "user-guide.md",
    "cli-reference.md",
    "desktop-editor.md",
    "installation.md",
    "codex-integration.md",
    "mcp-guide.md",
    "roadmap.md",
    "compatibility-0.2.0.md",
    "compatibility-0.3.0-beta.1.md",
    "compatibility-policy.md",
    "known-limitations-0.2.0.md",
    "known-limitations-0.3.0-beta.1.md",
)
LOCALIZED_ROOT_PAIR = ("README.md", "README.en.md")
LOCALE_ROOTS = {"zh-CN": "docs/zh-CN", "en": "docs/en"}
FEATURE_HEADINGS = (
    "用户目标",
    "使用入口",
    "CLI / Studio / MCP 对应关系",
    "数据与配置变化",
    "安全和失败行为",
    "兼容性与迁移",
    "测试与验收",
    "当前限制",
)
PUBLIC_TEXT_ROOTS = (
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs",
    ".agents/skills/qbank",
    ".agents/skills/qbank-digitize",
    "examples",
)
SOURCE_PREFIXES = (
    "src/qbank/",
    "apps/studio/",
    "protocol/",
    "scripts/build.py",
    "scripts/check.py",
)
INTERFACE_PREFIXES = (
    "src/qbank/commands/",
    "src/qbank/mcp/",
    "src/qbank/studio_sidecar/",
    "protocol/",
)
INTERFACE_FILES = {"src/qbank/cli.py", "src/qbank/codex_manifest.py"}
SCHEMA_PREFIXES = ("schemas/", "src/qbank/models/")
SCHEMA_FILES = {
    "src/qbank/schemas.py",
    "src/qbank/config.py",
    "src/qbank/resources/init/qbank.yaml",
}
DOC_PREFIXES = ("docs/", ".agents/skills/")
DOC_FILES = {
    "README.md",
    "README.en.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "AGENTS.md",
    "docs/monorepo-development.md",
}
PRIVATE_PATTERN = re.compile(
    r"(?i)(?:[A-Z]:[\\/](?:Users|project|Program Files|tools)[\\/][^\s`'\"<>]*|"
    r"\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9$._-]+(?:\\[^\s`'\"<>]+)+|"
    r"orangeofcarl0@gmail\.com)"
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
QBANK_LINE = re.compile(r"^\s*qbank\s+([a-z0-9-]+)(?:\s+([a-z0-9-]+))?", re.MULTILINE)
COMMAND_BLOCK = re.compile(r"```(?:powershell|shell|bash|console)?\s*\n(.*?)```", re.DOTALL)
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
ENGLISH_WORD = re.compile(r"\b[A-Za-z]{2,}\b")
FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`]*`")
MARKDOWN_LINK_WITH_LABEL = re.compile(r"!?\[[^\]]*]\([^)]+\)")
HTML_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def _check(name: str, failures: Iterable[str], success: str) -> Check:
    items = sorted(set(failures))
    return Check(name, not items, success if not items else "; ".join(items))


def _command_paths() -> tuple[set[tuple[str, ...]], set[tuple[str, ...]]]:
    nodes: set[tuple[str, ...]] = set()
    leaves: set[tuple[str, ...]] = set()

    def visit(command: object, prefix: tuple[str, ...]) -> None:
        children = getattr(command, "commands", None)
        if not isinstance(children, Mapping) or not children:
            leaves.add(prefix)
            return
        for name, child in children.items():
            path = (*prefix, str(name))
            nodes.add(path)
            visit(child, path)

    visit(get_command(app), ())
    return nodes, leaves


def _required_files(root: Path) -> Check:
    missing = [path for path in PUBLIC_FILES if not (root / path).is_file()]
    return _check("required-public-files", missing, f"{len(PUBLIC_FILES)} files present")


def _markdown_files(root: Path) -> list[Path]:
    files = [root / name for name in PUBLIC_FILES if name.endswith(".md")]
    files.extend((root / "docs").rglob("*.md"))
    return sorted(set(path for path in files if path.is_file()))


def _local_links(root: Path) -> Check:
    broken: list[str] = []
    for source in _markdown_files(root):
        text = source.read_text(encoding="utf-8")
        for raw in MARKDOWN_LINK.findall(text):
            target = raw.strip().strip("<>").split("#", maxsplit=1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "data:")):
                continue
            if not (source.parent / target).resolve().exists():
                broken.append(f"{source.relative_to(root)} -> {target}")
    return _check("local-markdown-links", broken, "all local links resolve")


def _feature_template(root: Path) -> Check:
    text = (root / "docs/features/_template.md").read_text(encoding="utf-8")
    missing = [heading for heading in FEATURE_HEADINGS if f"## {heading}" not in text]
    return _check("feature-template", missing, "all required sections present")


def _localized_paths() -> tuple[tuple[str, str], ...]:
    pairs = [(LOCALIZED_ROOT_PAIR[0], LOCALIZED_ROOT_PAIR[1])]
    pairs.extend(
        (
            f"{LOCALE_ROOTS['zh-CN']}/{name}",
            f"{LOCALE_ROOTS['en']}/{name}",
        )
        for name in LOCALIZED_DOCUMENTS
        if name != "README.md"
    )
    pairs.append(("docs/zh-CN/README.md", "docs/en/README.md"))
    return tuple(pairs)


def _prose_without_markup(text: str) -> str:
    text = FENCED_CODE.sub("", text)
    text = INLINE_CODE.sub("", text)
    text = MARKDOWN_LINK_WITH_LABEL.sub("", text)
    return HTML_TAG.sub("", text)


def _localized_documentation(root: Path) -> list[Check]:
    missing: list[str] = []
    navigation: list[str] = []
    mixed: list[str] = []
    for zh_relative, en_relative in _localized_paths():
        zh_path = root / zh_relative
        en_path = root / en_relative
        if not zh_path.is_file():
            missing.append(zh_relative)
        if not en_path.is_file():
            missing.append(en_relative)
        if not zh_path.is_file() or not en_path.is_file():
            continue
        zh_text = zh_path.read_text(encoding="utf-8")
        en_text = en_path.read_text(encoding="utf-8")
        if Path(en_relative).name not in zh_text and "README.en.md" not in zh_text:
            navigation.append(f"{zh_relative} -> {en_relative}")
        if Path(zh_relative).name not in en_text and "README.md" not in en_text:
            navigation.append(f"{en_relative} -> {zh_relative}")
        if CJK.search(_prose_without_markup(en_text)):
            mixed.append(f"{en_relative}: CJK prose in English document")
        zh_prose = _prose_without_markup(zh_text)
        for line_number, line in enumerate(zh_prose.splitlines(), start=1):
            if CJK.search(line) or len(ENGLISH_WORD.findall(line)) < 8:
                continue
            mixed.append(f"{zh_relative}:{line_number}: English prose in Chinese document")
    return [
        _check(
            "localized-document-pairs", missing, f"{len(_localized_paths())} locale pairs present"
        ),
        _check("localized-navigation", navigation, "all localized pages link across languages"),
        _check("localized-language-purity", mixed, "localized prose is separated by language"),
    ]


def _cli_documentation(root: Path, leaves: set[tuple[str, ...]]) -> Check:
    missing: list[str] = []
    for locale in LOCALE_ROOTS:
        text = (root / LOCALE_ROOTS[locale] / "cli-reference.md").read_text(encoding="utf-8")
        missing.extend(
            f"{locale}: qbank {' '.join(path)}"
            for path in leaves
            if f"`qbank {' '.join(path)}`" not in text
        )
    return _check(
        "cli-reference",
        missing,
        f"{len(leaves)} public commands documented in {len(LOCALE_ROOTS)} locales",
    )


def _manifest_consistency(root: Path, nodes: set[tuple[str, ...]]) -> list[Check]:
    matrix = (root / "docs/features/capability-matrix.md").read_text(encoding="utf-8")
    missing_paths: list[str] = []
    missing_matrix: list[str] = []
    for capability in INTEGRATION_CAPABILITIES:
        values = (capability.name, capability.mcp_tool, capability.resource)
        missing_matrix.extend(value for value in values if value and value not in matrix)
        if capability.cli_command:
            command = "qbank " + " ".join(capability.cli_command)
            if capability.cli_command not in nodes:
                missing_paths.append(command)
            if command not in matrix:
                missing_matrix.append(command)
    return [
        _check("manifest-cli", missing_paths, "all manifest CLI paths exist"),
        _check(
            "manifest-capability-docs",
            missing_matrix,
            f"{len(INTEGRATION_CAPABILITIES)} capabilities documented",
        ),
    ]


def _skill_consistency(root: Path) -> list[Check]:
    packaged = root / "src/qbank/resources/init/codex/skill"
    repository = root / ".agents/skills/qbank"
    drift = [
        relative
        for relative in SKILL_FILES
        if (packaged / relative).read_bytes() != (repository / relative).read_bytes()
    ]
    command_reference = (repository / "references/command-reference.md").read_text(encoding="utf-8")
    missing = [
        "qbank " + " ".join(command)
        for command in REQUIRED_COMMANDS
        if "qbank " + " ".join(command) not in command_reference
    ]
    agents_match = (root / "AGENTS.md").read_bytes() == (
        root / "src/qbank/resources/init/AGENTS.md"
    ).read_bytes()
    return [
        Check(
            "packaged-agents-mirror",
            agents_match,
            "root and packaged AGENTS.md match" if agents_match else "AGENTS.md mirror drift",
        ),
        _check("packaged-skill-mirror", drift, f"{len(SKILL_FILES)} Skill files match"),
        _check("skill-command-reference", missing, "all required workflow commands documented"),
    ]


def _public_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative in PUBLIC_TEXT_ROOTS:
        path = root / relative
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                candidate
                for candidate in path.rglob("*")
                if candidate.is_file()
                and candidate.suffix.lower()
                in {".md", ".yaml", ".yml", ".json", ".jsonl", ".csv", ".txt"}
            )
    return sorted(set(files))


def _public_data_safety(root: Path) -> Check:
    unsafe: list[str] = []
    for path in _public_text_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if PRIVATE_PATTERN.search(text):
            unsafe.append(str(path.relative_to(root)))
    return _check("public-data-safety", unsafe, "no machine paths or private identity found")


def _monorepo_contract(root: Path) -> Check:
    failures: list[str] = []
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((root / "apps/studio/package.json").read_text(encoding="utf-8"))
    tauri = json.loads((root / "apps/studio/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    protocol = json.loads((root / "protocol/studio-protocol-v1.json").read_text(encoding="utf-8"))
    if project["project"]["version"] != "0.3.0b1":
        failures.append("Python package is not 0.3.0b1")
    if package["version"] != "0.3.0-beta.1" or tauri["version"] != "0.3.0-beta.1":
        failures.append("Studio display versions are not 0.3.0-beta.1")
    if protocol["protocolVersion"] != "1.0":
        failures.append("Studio Protocol is not 1.0")
    for relative in (
        "src/qbank/studio_sidecar",
        "src/qbank/legacy_qt",
        "apps/studio/src",
        "apps/studio/src-tauri",
        "apps/studio/tests",
        "scripts/check.py",
        "scripts/build.py",
        "scripts/change-impact.json",
    ):
        if not (root / relative).exists():
            failures.append(f"missing monorepo path: {relative}")
    guide = (root / "docs/monorepo-development.md").read_text(encoding="utf-8")
    for command in (
        "python scripts/check.py fast",
        "python scripts/check.py integration",
        "python scripts/check.py release",
        "python scripts/build.py wheel",
        "python scripts/build.py studio",
        "python scripts/build.py all",
    ):
        if command not in guide:
            failures.append(f"undocumented monorepo command: {command}")
    return _check("studio-monorepo-contract", failures, "versions, paths, and entry points agree")


def _run(root: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, "-m", "qbank", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def _readme_examples(root: Path, nodes: set[tuple[str, ...]]) -> Check:
    groups = {path[0] for path in nodes if len(path) > 1}
    invalid: list[str] = []
    for relative in LOCALIZED_ROOT_PAIR:
        readme = (root / relative).read_text(encoding="utf-8")
        for block in COMMAND_BLOCK.findall(readme):
            for first, second in QBANK_LINE.findall(block):
                path = (first, second) if first in groups and second else (first,)
                if path not in nodes:
                    invalid.append(f"{relative}: qbank {' '.join(path)}")
    with tempfile.TemporaryDirectory(prefix="qbank-docs-sync-") as temporary:
        temp_root = Path(temporary)
        bank = temp_root / "demo-bank"
        commands = (
            (["--help"], root),
            (["init", str(bank), "--format", "json"], root),
            (["doctor", "--format", "json"], bank),
            (["schema", "--format", "json"], bank),
            (["validate", "--format", "json"], root / "examples/public-demo"),
        )
        for args, cwd in commands:
            result = _run(root, args, cwd)
            if result.returncode != 0:
                invalid.append(f"{' '.join(args)} -> exit {result.returncode}")
    return _check("readme-examples", invalid, "bilingual paths and safe smoke commands pass")


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


def _default_base(root: Path) -> str | None:
    result = _git(root, ["describe", "--tags", "--abbrev=0"])
    return result.stdout.strip() if result.returncode == 0 else None


def _changed_files(root: Path, base: str | None) -> set[str]:
    changed: set[str] = set()
    if base and base != "0" * 40:
        result = _git(root, ["diff", "--name-only", f"{base}...HEAD"])
        if result.returncode == 0:
            changed.update(result.stdout.splitlines())
    for args in (["diff", "--name-only"], ["ls-files", "--others", "--exclude-standard"]):
        result = _git(root, args)
        if result.returncode == 0:
            changed.update(result.stdout.splitlines())
    return {path.replace("\\", "/") for path in changed if path}


def _has_prefix(paths: set[str], prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefixes) for path in paths)


def _delta_policy(root: Path, base: str | None) -> Check:
    changed = _changed_files(root, base or _default_base(root))
    failures: list[str] = []
    docs_changed = any(path in DOC_FILES or path.startswith(DOC_PREFIXES) for path in changed)
    source_changed = _has_prefix(changed, SOURCE_PREFIXES)
    interface_changed = _has_prefix(changed, INTERFACE_PREFIXES) or bool(changed & INTERFACE_FILES)
    schema_changed = _has_prefix(changed, SCHEMA_PREFIXES) or bool(changed & SCHEMA_FILES)
    feature_doc_changed = any(
        path.startswith("docs/features/")
        and path not in {"docs/features/README.md", "docs/features/_template.md"}
        for path in changed
    )
    if source_changed and (not docs_changed or "CHANGELOG.md" not in changed):
        failures.append("source changes require affected documentation and CHANGELOG")
    if interface_changed and not (
        "docs/cli-reference.md" in changed
        or "docs/codex-integration.md" in changed
        or feature_doc_changed
    ):
        failures.append("CLI/MCP/manifest changes require interface documentation")
    if schema_changed and not (
        "docs/compatibility-policy.md" in changed
        and "CHANGELOG.md" in changed
        and feature_doc_changed
    ):
        failures.append("Schema/config changes require compatibility, feature, and migration notes")
    for zh_relative, en_relative in _localized_paths():
        if (zh_relative in changed) != (en_relative in changed):
            failures.append(f"localized pair must change together: {zh_relative} / {en_relative}")
    return _check("change-documentation-policy", failures, f"{len(changed)} changed files assessed")


def run_checks(root: Path, *, base: str | None = None, skip_examples: bool = False) -> list[Check]:
    nodes, leaves = _command_paths()
    checks = [
        _required_files(root),
        _local_links(root),
        _feature_template(root),
        *_localized_documentation(root),
        _cli_documentation(root, leaves),
        *_manifest_consistency(root, nodes),
        *_skill_consistency(root),
        _monorepo_contract(root),
        _public_data_safety(root),
        _delta_policy(root, base),
    ]
    if not skip_examples:
        checks.append(_readme_examples(root, nodes))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base")
    parser.add_argument("--skip-examples", action="store_true")
    args = parser.parse_args()
    checks = run_checks(args.root.resolve(), base=args.base, skip_examples=args.skip_examples)
    for check in checks:
        print(f"{'PASS' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    failures = sum(not check.ok for check in checks)
    print(f"docs-sync: {'PASS' if failures == 0 else 'FAIL'} ({len(checks)} checks)")
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
