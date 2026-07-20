"""Rollback-capable artifact and copied-resource commits."""

from __future__ import annotations

from pathlib import Path

from qbank.errors import ExportError
from qbank.transaction import MutationTransaction

AssetCopyPlan = dict[str, tuple[Path, Path]]


def commit_artifact(
    output: Path,
    content: str | bytes,
    assets: AssetCopyPlan,
) -> None:
    """Commit one artifact and its assets without leaving partial output."""
    if output.is_dir():
        raise ExportError(f"artifact output is a directory: {output}")
    destinations = {destination for _, destination in assets.values()}
    if output in destinations:
        raise ExportError(f"artifact output conflicts with a copied asset: {output}")
    transaction = MutationTransaction()
    if isinstance(content, str):
        transaction.write(output, content)
    else:
        transaction.write_bytes(output, content)
    try:
        for source, destination in assets.values():
            transaction.write_bytes(destination, source.read_bytes())
        transaction.commit()
    except OSError as exc:
        raise ExportError(f"could not write artifact: {exc}") from exc
