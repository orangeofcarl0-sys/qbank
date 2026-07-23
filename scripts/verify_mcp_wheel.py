"""Verify an installed qbank wheel through a real MCP STDIO handshake."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from qbank import __version__
from qbank.project import initialize_project


async def _verify() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="qbank-wheel-stdio-") as temporary:
        root = initialize_project(Path(temporary) / "bank")
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "qbank", "mcp", "--repository", str(root)],
            cwd=str(root),
        )
        async with (
            stdio_client(parameters) as streams,
            ClientSession(*streams) as session,
        ):
            initialized = await session.initialize()
            tools = await session.list_tools()
            status = await session.call_tool("repository_status", {})
            return {
                "qbank_version": __version__,
                "server": initialized.serverInfo.name,
                "tool_count": len(tools.tools),
                "status_ok": bool(status.structuredContent["ok"]),
            }


def main() -> None:
    print(json.dumps(asyncio.run(_verify()), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
