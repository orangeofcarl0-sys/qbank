"""Top-level Click usage-error handling for machine-readable CLI requests."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from typer.core import TyperGroup

from qbank.errors import ExitCode
from qbank.models import DiagnosticCode

if TYPE_CHECKING:
    from click import echo
    from click.exceptions import Abort, Exit, UsageError
else:
    from typer import _click

    Abort = _click.exceptions.Abort
    Exit = _click.exceptions.Exit
    UsageError = _click.exceptions.UsageError
    echo = _click.echo


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
        except UsageError as exc:
            if _requests_json(arguments):
                echo(
                    json.dumps(
                        {
                            "ok": False,
                            "code": DiagnosticCode.CLI_USAGE,
                            "error": exc.format_message(),
                            "exit_code": int(ExitCode.CLI_USAGE),
                        },
                        ensure_ascii=False,
                    )
                )
                raise SystemExit(int(ExitCode.CLI_USAGE)) from None
            if not standalone_mode:
                raise
            exc.show()
            raise SystemExit(exc.exit_code) from None
        except Exit as exc:
            raise SystemExit(exc.exit_code) from None
        except Abort:
            if standalone_mode:
                echo("Aborted!", err=True)
                raise SystemExit(int(ExitCode.GENERAL)) from None
            raise
