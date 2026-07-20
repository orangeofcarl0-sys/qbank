"""Optional lightweight desktop-editor command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from qbank.cli_support import abort
from qbank.errors import DependencyMissingError


def desktop_command(
    project: Annotated[
        Path | None,
        typer.Option("--project", help="qbank project root; defaults to upward discovery."),
    ] = None,
) -> None:
    """Launch the PySide6 Markdown/TeX question editor."""
    try:
        from qbank.desktop import launch

        code = launch(project.resolve() if project is not None else None)
        if code:
            raise typer.Exit(code=code)
    except ModuleNotFoundError as exc:
        if exc.name is not None and exc.name.startswith("PySide6"):
            abort(
                DependencyMissingError("dependency_missing: install qbank with the 'desktop' extra")
            )
        raise
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc)
