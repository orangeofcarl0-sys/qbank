"""Top-level Click usage-error handling for machine-readable CLI requests."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any, Protocol, cast

from click import echo
from typer.core import TyperGroup

from qbank.errors import ExitCode
from qbank.models import DiagnosticCode


def _option_value(arguments: Sequence[str], name: str) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == name and index + 1 < len(arguments):
            return arguments[index + 1]
        prefix = f"{name}="
        if argument.startswith(prefix):
            return argument.removeprefix(prefix)
    return None


def _requests_json(arguments: Sequence[str]) -> bool:
    if arguments and arguments[0] == "export":
        return True
    if len(arguments) >= 2 and arguments[:2] == ["paper", "build"]:
        return _option_value(arguments, "--result-format") == "json"
    return _option_value(arguments, "--format") == "json"


def _exception_named(exc: Exception, name: str) -> bool:
    """Match public Click and Typer's vendored Click exceptions without private imports."""
    return any(base.__name__ == name for base in type(exc).__mro__)


class _UsageErrorLike(Protocol):
    exit_code: int

    def format_message(self) -> str: ...

    def show(self) -> None: ...


class _ExitLike(Protocol):
    exit_code: int


class JsonUsageGroup(TyperGroup):
    """Preserve Click usage behavior while honoring explicit JSON output."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        arguments = list(args) if args is not None else sys.argv[1:]
        try:
            result = super().main(
                args=arguments,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
            if isinstance(result, int) and result:
                raise SystemExit(result)
            return result
        except Exception as exc:
            if _exception_named(exc, "UsageError"):
                usage_error = cast(_UsageErrorLike, exc)
                if _requests_json(arguments):
                    echo(
                        json.dumps(
                            {
                                "ok": False,
                                "code": DiagnosticCode.CLI_USAGE,
                                "error": usage_error.format_message(),
                                "exit_code": int(ExitCode.CLI_USAGE),
                            },
                            ensure_ascii=False,
                        )
                    )
                    raise SystemExit(int(ExitCode.CLI_USAGE)) from None
                if not standalone_mode:
                    raise
                usage_error.show()
                raise SystemExit(usage_error.exit_code) from None
            if _exception_named(exc, "Exit"):
                raise SystemExit(cast(_ExitLike, exc).exit_code) from None
            if _exception_named(exc, "Abort"):
                if standalone_mode:
                    echo("Aborted!", err=True)
                    raise SystemExit(int(ExitCode.GENERAL)) from None
                raise
            raise
