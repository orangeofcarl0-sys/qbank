"""Executable entry point that reserves stdout for Studio Protocol messages."""

from __future__ import annotations

import sys
from io import TextIOWrapper
from typing import TextIO, cast


def main() -> None:
    cast(TextIOWrapper, sys.stdin).reconfigure(encoding="utf-8", errors="strict")
    cast(TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8", errors="strict")
    cast(TextIOWrapper, sys.stderr).reconfigure(encoding="utf-8", errors="backslashreplace")
    protocol_stdout: TextIO = sys.stdout
    sys.stdout = sys.stderr
    from qbank.studio_sidecar.server import run_server

    raise SystemExit(run_server(sys.stdin, protocol_stdout))


if __name__ == "__main__":
    main()
