"""Project-scoped Codex MCP configuration with deterministic dry-run support."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from qbank.context import ProjectContext
from qbank.errors import ConflictError, DataValidationError
from qbank.models import McpConfigChange, McpIntegrationStatus
from qbank.transaction import MutationTransaction

_START = "# qbank-mcp: start"
_END = "# qbank-mcp: end"
_SERVER_HEADER = "[mcp_servers.qbank]"


def mcp_integration_status(context: ProjectContext) -> McpIntegrationStatus:
    """Inspect registration and optional runtime without modifying the project."""
    path = _config_path(context)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    registered = _managed_block(context) in text
    sdk_available = importlib.util.find_spec("mcp") is not None
    codex_available, codex_message = _codex_cli_ready()
    ok = registered and sdk_available
    missing: list[str] = []
    if not registered:
        missing.append("project MCP registration is missing")
    if not sdk_available:
        missing.append("qbank[mcp] is not installed")
    if not codex_available:
        missing.append(codex_message)
    return McpIntegrationStatus(
        ok=ok,
        registered=registered,
        configuration=str(path),
        repository=str(context.root),
        sdk_available=sdk_available,
        codex_cli_available=codex_available,
        degraded=not (registered and sdk_available and codex_available),
        message="ready" if not missing else "; ".join(missing),
    )


def install_project_mcp(
    context: ProjectContext,
    *,
    dry_run: bool,
) -> McpConfigChange:
    """Append or refresh only qbank's marked project-local configuration block."""
    path = _config_path(context)
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = _managed_block(context)
    existing = _extract_block(before)
    if existing == block:
        return _config_result(context, "unchanged", dry_run, changed=False)
    if existing is None and _unmanaged_server_declared(before):
        raise ConflictError(
            "unmanaged [mcp_servers.qbank] already exists; remove or rename it explicitly"
        )
    without = _remove_block(before)
    after = without.rstrip() + ("\n\n" if without.strip() else "") + block + "\n"
    if dry_run:
        return _config_result(context, "install", True, changed=True)
    backup = _commit_config(context, path, before, after)
    return _config_result(context, "install", False, changed=True, backup=backup)


def uninstall_project_mcp(
    context: ProjectContext,
    *,
    dry_run: bool,
) -> McpConfigChange:
    """Remove only qbank's marked MCP block, preserving unrelated Codex settings."""
    path = _config_path(context)
    before = path.read_text(encoding="utf-8") if path.is_file() else ""
    if _extract_block(before) is None:
        return _config_result(context, "unchanged", dry_run, changed=False)
    after = _remove_block(before).rstrip()
    if after:
        after += "\n"
    if dry_run:
        return _config_result(context, "uninstall", True, changed=True)
    backup = _commit_config(context, path, before, after)
    return _config_result(context, "uninstall", False, changed=True, backup=backup)


def _managed_block(context: ProjectContext) -> str:
    repository = str(context.root)
    return "\n".join(
        (
            _START,
            _SERVER_HEADER,
            f"command = {json.dumps(sys.executable)}",
            f"args = [{', '.join(json.dumps(value) for value in ('-m', 'qbank', 'mcp', '--repository', repository))}]",
            f"cwd = {json.dumps(repository)}",
            "enabled = true",
            "required = false",
            "startup_timeout_sec = 10",
            "tool_timeout_sec = 120",
            _END,
        )
    )


def _extract_block(text: str) -> str | None:
    start = text.find(_START)
    end = text.find(_END)
    if start < 0 and end < 0:
        return None
    if start < 0 or end < start:
        raise DataValidationError("invalid qbank MCP marker pair in .codex/config.toml")
    return text[start : end + len(_END)]


def _remove_block(text: str) -> str:
    block = _extract_block(text)
    if block is None:
        return text
    return text.replace(block, "", 1).strip("\n")


def _unmanaged_server_declared(text: str) -> bool:
    return re.search(r"(?m)^\s*\[mcp_servers\.qbank\]\s*$", text) is not None


def _commit_config(
    context: ProjectContext,
    path: Path,
    before: str,
    after: str,
) -> str | None:
    transaction = MutationTransaction()
    backup: Path | None = None
    if before:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = context.paths.state / "codex-mcp-backups" / f"config-{stamp}.toml"
        transaction.write(backup, before)
    if after:
        transaction.write(path, after)
    else:
        transaction.delete(path)
    transaction.commit()
    return str(backup) if backup is not None else None


def _config_result(
    context: ProjectContext,
    action: str,
    dry_run: bool,
    *,
    changed: bool,
    backup: str | None = None,
) -> McpConfigChange:
    return McpConfigChange.model_validate(
        {
            "ok": True,
            "action": action,
            "dry_run": dry_run,
            "configuration": str(_config_path(context)),
            "repository": str(context.root),
            "changed": changed,
            "backup": backup,
        }
    )


def _config_path(context: ProjectContext) -> Path:
    return context.root / ".codex" / "config.toml"


def _codex_cli_ready() -> tuple[bool, str]:
    executable = shutil.which("codex")
    if executable is None:
        return False, "Codex CLI is unavailable; Desktop/IDE may still load project config"
    try:
        result = subprocess.run(
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Codex CLI cannot be executed: {type(exc).__name__}"
    if result.returncode:
        return False, f"Codex CLI returned exit code {result.returncode}"
    return True, "Codex CLI is ready"
