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
    """Launch QBank Studio Legacy, the retained PySide6 fallback."""
    try:
        from qbank.legacy_qt import launch

        code = launch(project.resolve() if project is not None else None)
        if code:
            raise typer.Exit(code=code)
    except ImportError as exc:
        missing = exc.name or ""
        if missing.startswith("PySide6") or "DLL load failed" in str(exc):
            abort(
                DependencyMissingError(
                    "dependency_missing: PySide6 could not be loaded; "
                    "reinstall qbank with the 'desktop' extra"
                )
            )
        raise
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc)
