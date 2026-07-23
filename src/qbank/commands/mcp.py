"""CLI boundary for the optional repository-bound MCP transport."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from qbank.errors import ExitCode


def mcp_command(
    repository: Annotated[
        Path,
        typer.Option(
            "--repository",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Bind the STDIO server to this exact qbank repository root.",
        ),
    ],
) -> None:
    """Run a local MCP server over STDIO; stdout is reserved for JSON-RPC."""
    try:
        from qbank.mcp.server import run_stdio_server
    except ImportError as exc:
        message = "MCP support is not installed; install qbank[mcp]"
        print(message, file=sys.stderr)
        raise typer.Exit(code=int(ExitCode.DEPENDENCY)) from exc
    run_stdio_server(repository)
