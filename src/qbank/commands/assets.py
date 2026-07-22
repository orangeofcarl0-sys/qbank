"""Logical question-asset CLI adapters."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import typer
from pydantic import ValidationError

from qbank.asset_operations import normalize_asset_references_in_context
from qbank.bootstrap import ProjectServices, create_project_services
from qbank.cli_support import (
    abort,
    discover_context,
    emit_json,
    emit_warnings,
    read_utf8,
    require_output_format,
    resolve_project_path,
)
from qbank.errors import DataValidationError, ExitCode
from qbank.models import (
    ASSET_ID_PATTERN,
    AssetCommandResult,
    AssetFormat,
    AssetMutationResult,
    AssetPackage,
    AssetPackageRepresentation,
    AssetRenderResult,
    AssetStatus,
)


def asset_list_command(
    question_id: Annotated[str, typer.Argument()],
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """List logical assets registered for one question."""
    try:
        require_output_format(output_format, "table", "json")
        services = _services_for_question(question_id)
        result = services.assets.list_assets(question_id)
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            for asset in result.assets:
                typer.echo(
                    f"{asset.asset_id}\t{asset.role}\t{asset.status.value}\t"
                    f"{len(asset.representations)} representations"
                )
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_show_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Show one logical asset and all representations."""
    try:
        require_output_format(output_format, "table", "json")
        services = _services_for_question(question_id)
        result = services.assets.show_asset(question_id, asset_id)
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            typer.echo(f"{result.asset.question_id}/{result.asset.asset_id}")
            typer.echo(f"Status: {result.asset.status.value}")
            typer.echo(f"Preferred editor: {result.asset.preferred_editor or '-'}")
            typer.echo(f"Preferred render: {result.asset.preferred_render or '-'}")
            for item in result.asset.representations:
                typer.echo(
                    f"- {item.representation_id}: {item.format.value} ({item.path or item.url})"
                )
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_ingest_command(
    question_id: Annotated[str, typer.Argument()],
    package_file: Annotated[Path, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    download: Annotated[bool, typer.Option("--download/--keep-remote")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Ingest one asset-package JSON without discarding source representations."""
    try:
        require_output_format(output_format, "table", "json")
        context = discover_context()
        services = create_project_services(context)
        path = resolve_project_path(context, package_file)
        package = _load_package(path)
        if package.question_id != question_id:
            raise DataValidationError(
                "asset_package_invalid: package question_id does not match the argument"
            )
        result = services.assets.ingest_package(
            package,
            path.parent,
            dry_run=dry_run,
            download=download,
        )
        _emit_mutation(result, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_add_command(
    question_id: Annotated[str, typer.Argument()],
    source: Annotated[str, typer.Argument()],
    asset_id: Annotated[str | None, typer.Option("--asset-id")] = None,
    role: Annotated[str, typer.Option("--role")] = "figure",
    representation_id: Annotated[
        str | None,
        typer.Option("--representation-id"),
    ] = None,
    source_format: Annotated[str | None, typer.Option("--source-format")] = None,
    purpose: Annotated[str, typer.Option("--purpose")] = "original",
    editable: Annotated[bool, typer.Option("--editable/--read-only")] = False,
    page: Annotated[int | None, typer.Option("--page")] = None,
    crop: Annotated[str | None, typer.Option("--crop")] = None,
    download: Annotated[bool, typer.Option("--download/--keep-remote")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Add a file, Base64/data URI, TikZ, Ipe, PDF region, or URL."""
    try:
        require_output_format(output_format, "table", "json")
        context = discover_context()
        services = create_project_services(context)
        _require_question(services, question_id)
        package, package_root = _source_package(
            question_id,
            source,
            asset_id=asset_id,
            role=role,
            representation_id=representation_id,
            source_format=source_format,
            purpose=purpose,
            editable=editable,
            page=page,
            crop=crop,
        )
        result = services.assets.ingest_package(
            package,
            package_root,
            dry_run=dry_run,
            download=download,
        )
        _emit_mutation(result, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_open_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Open the selected preview with the system default application."""
    _asset_command(
        question_id,
        asset_id,
        action="open",
        dry_run=dry_run,
        output_format=output_format,
    )


def asset_edit_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Open only the registered preferred editable representation."""
    _asset_command(
        question_id,
        asset_id,
        action="edit",
        dry_run=dry_run,
        output_format=output_format,
    )


def asset_render_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    render_format: Annotated[
        list[str] | None,
        typer.Option("--render-format"),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Render a registered Ipe source to immutable PDF/SVG/PNG versions."""
    try:
        require_output_format(output_format, "table", "json")
        services = _services_for_question(question_id)
        formats = _render_formats(render_format)
        result = services.assets.render_asset(
            question_id,
            asset_id,
            formats=formats,
            dry_run=dry_run,
        )
        _emit_mutation(result, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_replace_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    file: Annotated[Path, typer.Argument()],
    representation_id: Annotated[
        str | None,
        typer.Option("--representation-id"),
    ] = None,
    purpose: Annotated[str, typer.Option("--purpose")] = "replacement",
    editable: Annotated[bool, typer.Option("--editable/--read-only")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Add and select a replacement version while retaining every prior file."""
    try:
        require_output_format(output_format, "table", "json")
        context = discover_context()
        services = create_project_services(context)
        _require_question(services, question_id)
        path = resolve_project_path(context, file)
        format_ = _format_from_name(path.name)
        representation = AssetPackageRepresentation(
            representation_id=representation_id or _safe_id(path.stem, "replacement"),
            format=format_,
            path=path.name,
            purpose=purpose,
            editable=editable or format_ in {AssetFormat.IPE, AssetFormat.TIKZ},
        )
        result = services.assets.replace(
            question_id,
            asset_id,
            representation,
            path.parent,
            dry_run=dry_run,
        )
        _emit_mutation(result, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_set_render_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    representation_id: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Set the preferred rendered representation."""
    _set_preference(
        question_id,
        asset_id,
        representation_id,
        kind="render",
        dry_run=dry_run,
        output_format=output_format,
    )


def asset_set_editor_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    representation_id: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Set the preferred editable representation."""
    _set_preference(
        question_id,
        asset_id,
        representation_id,
        kind="editor",
        dry_run=dry_run,
        output_format=output_format,
    )


def asset_finalize_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str, typer.Argument()],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Mark an asset final after validating its preferred render."""
    try:
        require_output_format(output_format, "table", "json")
        services = _services_for_question(question_id)
        result = services.assets.finalize(question_id, asset_id, dry_run=dry_run)
        _emit_mutation(result, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_normalize_command(
    question_id: Annotated[str, typer.Argument()],
    asset_id: Annotated[str | None, typer.Option("--asset-id")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Migrate preserved legacy path references to stable logical asset IDs."""
    try:
        require_output_format(output_format, "table", "json")
        context = discover_context()
        services = create_project_services(context)
        _require_question(services, question_id)
        if asset_id is not None:
            services.assets.show_asset(question_id, asset_id)
        result = normalize_asset_references_in_context(
            context,
            question_id,
            assets=services.assets,
            mutations=services.mutations,
            asset_id=asset_id,
            dry_run=dry_run,
        )
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            emit_warnings(result, output_format)
            typer.echo(
                f"{'Would normalize' if dry_run else 'Normalized'} {question_id}: "
                f"{len(result.changes)} field changes"
            )
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)


def asset_validate_command(
    output_format: Annotated[str, typer.Option("--format")] = "table",
) -> None:
    """Validate every asset manifest, owner, file, hash, and lifecycle state."""
    try:
        require_output_format(output_format, "table", "json")
        context = discover_context()
        services = create_project_services(context)
        snapshot = services.repository.scan()
        result = services.assets.validate_assets(
            known_question_ids={record.question.id for record in snapshot.records}
        )
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            typer.echo(
                f"{result.summary.assets} assets, "
                f"{result.summary.representations} representations, "
                f"{result.summary.errors} errors, {result.summary.warnings} warnings"
            )
            for item in result.issues:
                typer.echo(f"{item.severity}: [{item.code}] {item.message}", err=True)
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
        if not result.ok:
            raise typer.Exit(code=int(ExitCode.VALIDATION))
    except typer.Exit:
        raise
    except Exception as exc:
        abort(exc, output_format=output_format)


def _services_for_question(question_id: str) -> ProjectServices:
    context = discover_context()
    services = create_project_services(context)
    _require_question(services, question_id)
    return services


def _require_question(services: ProjectServices, question_id: str) -> None:
    snapshot = services.repository.scan()
    snapshot.require_consistent()
    snapshot.locate(question_id)


def _load_package(path: Path) -> AssetPackage:
    try:
        return AssetPackage.model_validate_json(read_utf8(path, label="asset package"))
    except ValidationError as exc:
        raise DataValidationError(f"asset_package_invalid: {exc}") from exc


def _source_package(
    question_id: str,
    source: str,
    *,
    asset_id: str | None,
    role: str,
    representation_id: str | None,
    source_format: str | None,
    purpose: str,
    editable: bool,
    page: int | None,
    crop: str | None,
) -> tuple[AssetPackage, Path]:
    representation, root, source_label = _source_representation(
        source,
        representation_id=representation_id,
        source_format=source_format,
        purpose=purpose,
        editable=editable,
        metadata=_pdf_metadata(page, crop),
    )
    identifier = asset_id or _safe_id(_source_stem(source), "asset")
    package = AssetPackage(
        schema_version="1.0",
        question_id=question_id,
        asset_id=identifier,
        role=role,
        representations=[representation],
        provenance={"input": "qbank asset add", "source": source_label},
        suggested_editor=(representation.representation_id if representation.editable else None),
        suggested_render=(
            representation.representation_id
            if representation.url is not None
            or representation.format.value
            in {
                "png",
                "jpeg",
                "pdf",
                "svg",
                "webp",
                "gif",
                "bmp",
            }
            else None
        ),
        status=AssetStatus.RAW,
    )
    return package, root


def _source_representation(
    source: str,
    *,
    representation_id: str | None,
    source_format: str | None,
    purpose: str,
    editable: bool,
    metadata: dict[str, object],
) -> tuple[AssetPackageRepresentation, Path, str]:
    path = _existing_source_path(source)
    if path is not None:
        resolved = path.resolve()
        format_ = _asset_format(source_format) if source_format else _format_from_name(path.name)
        return (
            AssetPackageRepresentation(
                representation_id=representation_id or _default_representation_id(format_),
                format=format_,
                path=resolved.name,
                purpose=purpose,
                editable=editable or format_ in {AssetFormat.IPE, AssetFormat.TIKZ},
                metadata=metadata,
            ),
            resolved.parent,
            str(resolved),
        )
    format_ = _asset_format(source_format) if source_format else _format_from_source(source)
    values: dict[str, object] = {
        "representation_id": representation_id or _default_representation_id(format_),
        "format": format_,
        "purpose": purpose,
        "editable": editable or format_ in {AssetFormat.IPE, AssetFormat.TIKZ},
        "metadata": metadata,
    }
    source_label = "inline"
    if source.startswith(("http://", "https://")):
        values["url"] = source
        source_label = source
    elif source.startswith("data:"):
        values["data_uri"] = source
        source_label = "data-uri"
    elif "\\begin{tikzpicture}" in source:
        values["inline_tikz"] = source
        source_label = "inline-tikz"
    else:
        values["base64"] = source
        source_label = "base64"
    return AssetPackageRepresentation.model_validate(values), Path.cwd(), source_label


def _asset_command(
    question_id: str,
    asset_id: str,
    *,
    action: Literal["open", "edit"],
    dry_run: bool,
    output_format: str,
) -> None:
    try:
        require_output_format(output_format, "table", "json")
        service = _services_for_question(question_id).assets
        result = (
            service.open_asset(question_id, asset_id, dry_run=dry_run)
            if action == "open"
            else service.edit_asset(question_id, asset_id, dry_run=dry_run)
        )
        if output_format == "json":
            emit_json(result)
        elif output_format == "table":
            typer.echo(f"{'Would launch' if dry_run else 'Launched'}: {result.target}")
        else:
            raise DataValidationError(f"unsupported output format: {output_format}")
    except Exception as exc:
        abort(exc, output_format=output_format)


def _set_preference(
    question_id: str,
    asset_id: str,
    representation_id: str,
    *,
    kind: Literal["editor", "render"],
    dry_run: bool,
    output_format: str,
) -> None:
    try:
        require_output_format(output_format, "table", "json")
        service = _services_for_question(question_id).assets
        result = service.set_preference(
            question_id,
            asset_id,
            representation_id,
            kind=kind,
            dry_run=dry_run,
        )
        _emit_mutation(result, output_format)
    except Exception as exc:
        abort(exc, output_format=output_format)


def _emit_mutation(
    result: AssetMutationResult | AssetCommandResult | AssetRenderResult,
    output_format: str,
) -> None:
    if output_format == "json":
        emit_json(result)
        return
    if output_format != "table":
        raise DataValidationError(f"unsupported output format: {output_format}")
    emit_warnings(result, output_format)
    action = result.action
    asset_id = result.asset_id
    dry_run = result.dry_run
    typer.echo(f"{'Would ' if dry_run else ''}{action}: {asset_id}")


def _render_formats(values: list[str] | None) -> tuple[AssetFormat, ...]:
    requested = values or ["pdf", "svg", "png"]
    formats = tuple(_asset_format(item) for item in requested)
    if any(item not in {AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG} for item in formats):
        raise DataValidationError("invalid_filter: Ipe render formats are pdf, svg, and png")
    return formats


def _asset_format(value: str) -> AssetFormat:
    try:
        return AssetFormat(value.lower())
    except ValueError as exc:
        raise DataValidationError(f"invalid_filter: unsupported asset format: {value}") from exc


def _format_from_source(source: str) -> AssetFormat:
    if source.startswith("data:"):
        media = source[5:].partition(";")[0].partition(",")[0]
        return {
            "image/png": AssetFormat.PNG,
            "image/jpeg": AssetFormat.JPEG,
            "application/pdf": AssetFormat.PDF,
            "image/svg+xml": AssetFormat.SVG,
        }.get(media, AssetFormat.OTHER)
    if source.startswith(("http://", "https://")):
        name = Path(urlsplit(source).path).name
        return _format_from_name(name) if Path(name).suffix else AssetFormat.URL
    if "\\begin{tikzpicture}" in source:
        return AssetFormat.TIKZ
    return AssetFormat.OTHER


def _format_from_name(name: str) -> AssetFormat:
    suffix = Path(name).suffix.lower()
    try:
        return {
            ".png": AssetFormat.PNG,
            ".jpg": AssetFormat.JPEG,
            ".jpeg": AssetFormat.JPEG,
            ".pdf": AssetFormat.PDF,
            ".svg": AssetFormat.SVG,
            ".tex": AssetFormat.TIKZ,
            ".ipe": AssetFormat.IPE,
            ".webp": AssetFormat.WEBP,
            ".gif": AssetFormat.GIF,
            ".bmp": AssetFormat.BMP,
        }[suffix]
    except KeyError as exc:
        raise DataValidationError(f"invalid_filter: unsupported asset file: {name}") from exc


def _default_representation_id(format_: AssetFormat) -> str:
    if format_ == AssetFormat.IPE:
        return "ipe-source"
    if format_ == AssetFormat.TIKZ:
        return "tikz-source"
    return "original"


def _source_stem(source: str) -> str:
    if source.startswith(("http://", "https://")):
        return Path(urlsplit(source).path).stem or "remote"
    if not _inline_source(source):
        try:
            path = Path(source)
            if path.suffix:
                return path.stem
        except OSError:
            pass
    return f"asset-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:8]}"


def _existing_source_path(source: str) -> Path | None:
    """Return a readable local source without treating large inline data as a path."""
    if _inline_source(source):
        return None
    try:
        candidate = Path(source).expanduser()
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _inline_source(source: str) -> bool:
    return source.startswith(("http://", "https://", "data:")) or "\\begin{tikzpicture}" in source


def _safe_id(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    candidate = normalized or fallback
    if re.fullmatch(ASSET_ID_PATTERN, candidate) is None:
        raise DataValidationError(f"asset_package_invalid: unsafe asset ID: {candidate}")
    return candidate


def _pdf_metadata(page: int | None, crop: str | None) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if page is not None:
        if page < 1:
            raise DataValidationError("invalid_filter: PDF page must be at least 1")
        metadata["page"] = page
    if crop is not None:
        try:
            values = [float(item.strip()) for item in crop.split(",")]
        except ValueError as exc:
            raise DataValidationError("invalid_filter: crop must be x0,y0,x1,y1") from exc
        if len(values) != 4 or values[2] <= values[0] or values[3] <= values[1]:
            raise DataValidationError("invalid_filter: crop must be x0,y0,x1,y1")
        metadata["crop"] = values
    return metadata
