"""Regression coverage for native multi-representation logical assets."""

from __future__ import annotations

import base64
import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from qbank.application.assets import AssetApplicationService
from qbank.asset_operations import normalize_asset_references_in_context
from qbank.asset_server import create_asset_management_server
from qbank.assets import AssetService
from qbank.bootstrap import create_project_services
from qbank.cli import app
from qbank.commands import assets as asset_commands
from qbank.context import ProjectContext
from qbank.domain import RenderedAsset, asset_legacy_references, select_asset_representation
from qbank.errors import (
    AssetCommandError,
    AssetConflictError,
    DataValidationError,
    IpeUnavailableError,
)
from qbank.infrastructure import ipe as ipe_infrastructure
from qbank.infrastructure.assets import AssetInputAdapter, FileAssetRepository
from qbank.infrastructure.ipe import IpeRenderAdapter, IpeToolchain, SafeAssetLauncher
from qbank.models import (
    AssetFormat,
    AssetManifest,
    AssetPackage,
    AssetPackageRepresentation,
    AssetRepresentation,
    AssetStatus,
    Question,
)
from qbank.operations import add_question
from qbank.preview import build_preview_in_context


def _package(
    question_id: str,
    asset_id: str,
    representations: list[AssetPackageRepresentation],
    **options: object,
) -> AssetPackage:
    return AssetPackage(
        schema_version="1.0",
        question_id=question_id,
        asset_id=asset_id,
        role="diagram",
        representations=representations,
        status=options.get("status", AssetStatus.RAW),
        suggested_editor=options.get("editor"),
        suggested_render=options.get("render"),
        provenance=options.get("provenance", {}),
    )


def _png_package(question_id: str, asset_id: str = "figure") -> AssetPackage:
    return _package(
        question_id,
        asset_id,
        [
            AssetPackageRepresentation(
                representation_id="original",
                format=AssetFormat.PNG,
                base64=base64.b64encode(b"png-data").decode("ascii"),
                purpose="original",
            )
        ],
        render="original",
        provenance={"legacy_references": ["assets/images/legacy.png"]},
    )


def _context(root: Path, config: Any) -> ProjectContext:
    return ProjectContext.from_config(root, config)


def _services(root: Path, config: Any) -> AssetApplicationService:
    return create_project_services(_context(root, config)).assets


def _add_logical_question(root: Path, config: Any, question: Question, asset_id: str) -> Question:
    logical = question.model_copy(
        update={
            "assets": [f"asset:{asset_id}"],
            "stem_md": f"![figure](asset:{asset_id})",
        }
    )
    add_question(root, config, logical)
    return logical


@dataclass
class _FakeRenderer:
    calls: list[tuple[Path, tuple[AssetFormat, ...], bool]] = field(default_factory=list)

    def render(
        self,
        source: Path,
        formats: tuple[AssetFormat, ...],
        *,
        execute: bool,
    ) -> tuple[RenderedAsset, ...]:
        self.calls.append((source, formats, execute))
        return tuple(
            RenderedAsset(
                format=format_,
                content=f"rendered-{format_.value}".encode("ascii"),
                command=("iperender.exe", format_.value, str(source)),
                metadata={"renderer": "fake-ipe"},
            )
            for format_ in formats
        )


@dataclass
class _FakeLauncher:
    calls: list[tuple[str, Path]] = field(default_factory=list)

    def open_file(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        self.calls.append(("open", path))
        return ("system-default", str(path))

    def open_url(self, url: str, *, execute: bool) -> tuple[str, ...]:
        del execute
        return ("system-browser", url)

    def open_directory(self, path: Path, *, execute: bool) -> tuple[str, ...]:
        self.calls.append(("directory", path))
        return ("system-default", str(path))

    def edit_file(
        self,
        path: Path,
        format_: AssetFormat,
        *,
        execute: bool,
    ) -> tuple[str, ...]:
        del format_, execute
        self.calls.append(("edit", path))
        return ("ipe.exe", str(path))


def _fake_service(root: Path, config: Any, renderer: _FakeRenderer) -> AssetApplicationService:
    context = _context(root, config)
    return AssetApplicationService(
        repository=FileAssetRepository(context),
        inputs=AssetInputAdapter(context),
        renderer=renderer,
        launcher=_FakeLauncher(),
    )


def test_asset_package_ingest_decodes_base64_and_preserves_hash(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    result = service.ingest_package(_png_package(question.id), root, dry_run=False)

    manifest = service.show_asset(question.id, "figure").asset
    assert result.action == "create"
    assert manifest.representations[0].content_hash
    assert service.repository.representation_path(manifest, "original").read_bytes() == b"png-data"


def test_package_ingest_is_idempotent_and_conflicts_on_changed_representation(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    package = _png_package(question.id)
    assert service.ingest_package(package, root, dry_run=False).action == "create"
    assert service.ingest_package(package, root, dry_run=False).action == "unchanged"
    changed = package.model_copy(
        update={
            "representations": [
                package.representations[0].model_copy(
                    update={"base64": base64.b64encode(b"changed").decode("ascii")}
                )
            ]
        }
    )
    with pytest.raises(AssetConflictError, match="asset_conflict"):
        service.ingest_package(changed, root, dry_run=False)


def test_inline_tikz_is_externalized_to_tex(project: tuple[Path, Any], question: Question) -> None:
    root, config = project
    service = _services(root, config)
    package = _package(
        question.id,
        "tikz",
        [
            AssetPackageRepresentation(
                representation_id="tikz-source",
                format=AssetFormat.TIKZ,
                inline_tikz="\\begin{tikzpicture}\\draw (0,0)--(1,1);\\end{tikzpicture}",
                purpose="source",
                editable=True,
            )
        ],
        editor="tikz-source",
    )
    service.ingest_package(package, root, dry_run=False)
    manifest = service.show_asset(question.id, "tikz").asset
    path = service.repository.representation_path(manifest, "tikz-source")
    assert path is not None and path.suffix == ".tex"
    assert "tikzpicture" in path.read_text(encoding="utf-8")


def test_external_url_is_retained_without_download(
    project: tuple[Path, Any], question: Question
) -> None:
    root, config = project
    service = _services(root, config)
    package = _package(
        question.id,
        "remote",
        [
            AssetPackageRepresentation(
                representation_id="remote-url",
                format=AssetFormat.URL,
                url="https://example.invalid/figure.png",
                purpose="reference",
            )
        ],
        render="remote-url",
    )
    service.ingest_package(package, root, dry_run=False)
    representation = service.show_asset(question.id, "remote").asset.representations[0]
    assert representation.url == "https://example.invalid/figure.png"
    assert representation.content_hash is None


def test_pdf_page_and_crop_metadata_survive_normalization(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    source = root / "incoming"
    source.mkdir()
    (source / "scan.pdf").write_bytes(b"%PDF-scan")
    service = _services(root, config)
    package = _package(
        question.id,
        "pdf-crop",
        [
            AssetPackageRepresentation(
                representation_id="scan",
                format=AssetFormat.PDF,
                path="scan.pdf",
                purpose="original",
                metadata={"page": 2, "crop": {"x": 1, "y": 2, "width": 3, "height": 4}},
            )
        ],
        render="scan",
    )
    service.ingest_package(package, source, dry_run=False)
    assert (
        service.show_asset(question.id, "pdf-crop").asset.representations[0].metadata["page"] == 2
    )


def test_ipe_source_renders_multiple_hash_versioned_derivatives(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    source = root / "incoming"
    source.mkdir()
    (source / "source.ipe").write_text("<ipe/>", encoding="utf-8")
    renderer = _FakeRenderer()
    service = _fake_service(root, config, renderer)
    package = _package(
        question.id,
        "ipe-figure",
        [
            AssetPackageRepresentation(
                representation_id="ipe-source",
                format=AssetFormat.IPE,
                path="source.ipe",
                purpose="source",
                editable=True,
            )
        ],
        editor="ipe-source",
    )
    service.ingest_package(package, source, dry_run=False)
    result = service.render_asset(
        question.id,
        "ipe-figure",
        formats=(AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG),
        dry_run=False,
    )
    manifest = service.show_asset(question.id, "ipe-figure").asset
    renders = [item for item in manifest.representations if item.purpose == "render"]
    assert len(result.generated) == 3
    assert {item.format for item in renders} == {AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG}
    assert all(item.derived_from == "ipe-source" for item in renders)
    assert renderer.calls[0][2] is True


def test_preferred_editor_and_render_can_be_switched(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    package = _package(
        question.id,
        "multi",
        [
            AssetPackageRepresentation(
                representation_id="source",
                format=AssetFormat.TIKZ,
                inline_tikz="x",
                purpose="source",
                editable=True,
            ),
            AssetPackageRepresentation(
                representation_id="preview", format=AssetFormat.PNG, base64="eA==", purpose="render"
            ),
        ],
        editor="source",
        render="preview",
    )
    service.ingest_package(package, root, dry_run=False)
    service.set_preference(question.id, "multi", "source", kind="editor", dry_run=False)
    service.set_preference(question.id, "multi", "preview", kind="render", dry_run=False)
    manifest = service.show_asset(question.id, "multi").asset
    assert (manifest.preferred_editor, manifest.preferred_render) == ("source", "preview")


def test_replace_keeps_original_representation_and_selects_versioned_copy(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    service.ingest_package(_png_package(question.id), root, dry_run=False)
    original = service.show_asset(question.id, "figure").asset
    original_path = service.repository.representation_path(original, "original")
    result = service.replace(
        question.id,
        "figure",
        AssetPackageRepresentation(
            representation_id="replacement",
            format=AssetFormat.PNG,
            base64=base64.b64encode(b"replacement-png").decode("ascii"),
            purpose="replacement",
        ),
        root,
        dry_run=False,
    )
    updated = service.show_asset(question.id, "figure").asset
    assert original_path is not None and original_path.read_bytes() == b"png-data"
    assert result.action == "replace"
    assert len(updated.representations) == 2
    assert updated.preferred_render and updated.preferred_render.startswith("replacement-")


def test_edit_uses_registered_ipe_source_only(
    project: tuple[Path, Any], question: Question
) -> None:
    root, config = project
    source = root / "incoming"
    source.mkdir()
    (source / "source.ipe").write_text("<ipe/>", encoding="utf-8")
    renderer = _FakeRenderer()
    service = _fake_service(root, config, renderer)
    service.ingest_package(
        _package(
            question.id,
            "editable",
            [
                AssetPackageRepresentation(
                    representation_id="ipe-source",
                    format=AssetFormat.IPE,
                    path="source.ipe",
                    purpose="source",
                    editable=True,
                )
            ],
            editor="ipe-source",
        ),
        source,
        dry_run=False,
    )
    result = service.edit_asset(question.id, "editable", dry_run=False)
    assert result.command[0] == "ipe.exe"
    assert result.representation_id == "ipe-source"


def test_missing_ipe_reports_stable_diagnostic(project: tuple[Path, Any]) -> None:
    root, config = project
    broken = config.model_copy(deep=True)
    broken.assets.editors.ipe.command = "definitely-not-an-ipe-executable"
    with pytest.raises(IpeUnavailableError, match="ipe_unavailable"):
        IpeToolchain.discover(ProjectContext.from_config(root, broken))


def test_package_path_escape_and_invalid_commandish_identifier_are_rejected(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    with pytest.raises(ValidationError):
        AssetPackageRepresentation(
            representation_id="bad;command",
            format=AssetFormat.PNG,
            path="../outside.png",
            purpose="original",
        )
    with pytest.raises(ValidationError):
        AssetPackageRepresentation(
            representation_id="outside",
            format=AssetFormat.PNG,
            path="../outside.png",
            purpose="original",
        )
    assert service.list_assets(question.id).assets == []


def test_legacy_reference_projects_to_registered_preferred_render(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    service.ingest_package(_png_package(question.id), root, dry_run=False)
    legacy = question.model_copy(
        update={
            "assets": ["assets/images/legacy.png"],
            "stem_md": "![old](assets/images/legacy.png)",
        }
    )
    projected, warnings = AssetService(_context(root, config), service).project_question(
        legacy, target="html"
    )
    assert projected.assets == [f"assets/{question.id}/figure/original.png"]
    assert "assets/" in projected.stem_md
    assert warnings[0].code == "asset_needs_redraw"


def test_logical_assets_validate_and_normalize_question_references(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    service.ingest_package(_png_package(question.id), root, dry_run=False)
    added = _add_logical_question(root, config, question, "figure")
    report = service.validate_assets(known_question_ids={added.id})
    assert report.ok
    assert (root / "assets" / question.id / "figure" / "asset.yaml").is_file()


def test_target_selection_prefers_pdf_for_pdf_and_svg_for_html() -> None:
    manifest = AssetManifest(
        schema_version="1.0",
        question_id="OPT-INT-0001",
        asset_id="formats",
        role="diagram",
        status=AssetStatus.FINAL,
        preferred_render="pdf",
        representations=[
            AssetRepresentation(
                representation_id="png",
                format=AssetFormat.PNG,
                path="image.png",
                purpose="render",
                content_hash="0" * 64,
            ),
            AssetRepresentation(
                representation_id="pdf",
                format=AssetFormat.PDF,
                path="image.pdf",
                purpose="render",
                content_hash="1" * 64,
            ),
            AssetRepresentation(
                representation_id="svg",
                format=AssetFormat.SVG,
                path="image.svg",
                purpose="render",
                content_hash="2" * 64,
            ),
        ],
    )
    assert select_asset_representation(manifest, "pdf").representation_id == "pdf"
    assert select_asset_representation(manifest, "html").representation_id == "svg"


def test_target_selection_covers_preferred_stale_and_incompatible_paths() -> None:
    fresh_preferred = AssetManifest(
        schema_version="1.0",
        question_id="OPT-INT-0001",
        asset_id="fresh-preferred",
        role="diagram",
        status=AssetStatus.FINAL,
        preferred_render="svg",
        representations=[
            AssetRepresentation(
                representation_id="svg",
                format=AssetFormat.SVG,
                path="image.svg",
                purpose="render",
                content_hash="3" * 64,
            )
        ],
    )
    assert select_asset_representation(fresh_preferred, "html").representation_id == "svg"
    assert select_asset_representation(fresh_preferred, "preview", requested="missing") is None

    incompatible = AssetManifest(
        schema_version="1.0",
        question_id="OPT-INT-0001",
        asset_id="incompatible",
        role="diagram",
        status=AssetStatus.RAW,
        representations=[
            AssetRepresentation(
                representation_id="pdf",
                format=AssetFormat.PDF,
                path="image.pdf",
                purpose="render",
                content_hash="4" * 64,
            )
        ],
    )
    assert select_asset_representation(incompatible, "preview") is None

    stale_preferred = AssetManifest(
        schema_version="1.0",
        question_id="OPT-INT-0001",
        asset_id="stale-preferred",
        role="diagram",
        status=AssetStatus.NEEDS_REDRAW,
        preferred_render="svg",
        representations=[
            AssetRepresentation(
                representation_id="pdf",
                format=AssetFormat.PDF,
                path="image.pdf",
                purpose="render",
                stale=True,
                content_hash="5" * 64,
            ),
            AssetRepresentation(
                representation_id="svg",
                format=AssetFormat.SVG,
                path="image.svg",
                purpose="render",
                stale=True,
                content_hash="6" * 64,
            ),
        ],
    )
    assert select_asset_representation(stale_preferred, "pdf").representation_id == "svg"


def test_asset_legacy_references_accepts_only_explicit_strings() -> None:
    assert asset_legacy_references(
        {
            "legacy_reference": "assets/legacy.svg",
            "original_asset_path": 42,
            "legacy_references": ["assets/one.png", None, "assets/two.pdf"],
        }
    ) == {"assets/legacy.svg", "assets/one.png", "assets/two.pdf"}


def test_needs_redraw_warning_is_emitted_for_paper_projection(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    service.ingest_package(
        _png_package(question.id).model_copy(update={"status": AssetStatus.NEEDS_REDRAW}),
        root,
        dry_run=False,
    )
    logical = _add_logical_question(root, config, question, "figure")
    _, warnings = AssetService(_context(root, config), service).project_question(
        logical, target="pdf"
    )
    assert [item.code for item in warnings] == ["asset_needs_redraw"]


def test_localhost_management_page_serves_registered_assets_and_finalizes(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    context = _context(root, config)
    services = create_project_services(context)
    services.assets.ingest_package(_png_package(question.id), root, dry_run=False)
    _add_logical_question(root, config, question, "figure")
    preview = build_preview_in_context(
        context, services.repository.scan(), services.renderer, services.assets
    )
    server, endpoint = create_asset_management_server(
        context,
        services.assets,
        services.renderer,
        questions=preview.questions,
        port=0,
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        dashboard = urllib.request.urlopen(endpoint.url, timeout=5).read().decode("utf-8")
        assert "资产管理" in dashboard and "figure" in dashboard
        file_url = f"{endpoint.url}_assets/{question.id}/figure/original"
        assert urllib.request.urlopen(file_url, timeout=5).read() == b"png-data"
        payload = json.dumps({}).encode("utf-8")
        request = urllib.request.Request(
            f"{endpoint.url}api/assets/{question.id}/figure/finalize",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "X-QBank-Token": server.manager.token},
        )
        assert json.loads(urllib.request.urlopen(request, timeout=5).read())["ok"]
        assert services.assets.show_asset(question.id, "figure").asset.status == AssetStatus.FINAL
        denied = urllib.request.Request(
            f"{endpoint.url}api/assets/{question.id}/figure/finalize",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(denied, timeout=5)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_chinese_space_windows_style_package_path_is_supported(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    source = root / "含 空格"
    source.mkdir()
    (source / "图 像.png").write_bytes(b"png")
    service = _services(root, config)
    package = _package(
        question.id,
        "chinese-path",
        [
            AssetPackageRepresentation(
                representation_id="source",
                format=AssetFormat.PNG,
                path="图 像.png",
                purpose="original",
            )
        ],
        render="source",
    )
    service.ingest_package(package, source, dry_run=False)
    assert (
        service.show_asset(question.id, "chinese-path").asset.representations[0].path
        == "source.png"
    )


def test_asset_cli_ingest_and_add_accept_machine_exchange_formats(
    cli_project: Path,
    question: Question,
    runner: CliRunner,
) -> None:
    package = _png_package(question.id)
    package_file = cli_project / "incoming-package.json"
    package_file.write_text(package.model_dump_json(), encoding="utf-8")

    dry_run = runner.invoke(
        app,
        ["asset", "ingest", question.id, str(package_file), "--dry-run", "--format", "json"],
    )
    assert dry_run.exit_code == 0 and json.loads(dry_run.stdout)["dry_run"]
    actual = runner.invoke(
        app,
        ["asset", "ingest", question.id, str(package_file), "--format", "json"],
    )
    assert actual.exit_code == 0 and json.loads(actual.stdout)["action"] == "create"
    add_question(cli_project, ProjectContext.from_root(cli_project).config, question)
    base64_add = runner.invoke(
        app,
        [
            "asset",
            "add",
            question.id,
            base64.b64encode(b"second").decode("ascii"),
            "--asset-id",
            "from-base64",
            "--format",
            "json",
        ],
    )
    assert base64_add.exit_code == 0 and json.loads(base64_add.stdout)["asset_id"] == "from-base64"


def test_asset_cli_full_lifecycle_covers_registered_operations(
    cli_project: Path,
    question: Question,
    runner: CliRunner,
) -> None:
    """Exercise the public commands without launching an external application."""

    legacy = question.model_copy(
        update={
            "assets": ["assets/images/legacy.png"],
            "stem_md": "![legacy](assets/images/legacy.png)",
        }
    )
    legacy_file = cli_project / "assets" / "images" / "legacy.png"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_bytes(b"legacy")
    add_question(cli_project, ProjectContext.from_root(cli_project).config, legacy)
    package_path = cli_project / "legacy-package.json"
    package_path.write_text(_png_package(question.id).model_dump_json(), encoding="utf-8")
    replacement = cli_project / "replacement.png"
    replacement.write_bytes(b"replacement")

    invocations = [
        ["asset", "ingest", question.id, str(package_path), "--format", "json"],
        [
            "asset",
            "add",
            question.id,
            "\\begin{tikzpicture}\\draw (0,0)--(1,1);\\end{tikzpicture}",
            "--asset-id",
            "tikz",
            "--format",
            "json",
        ],
        ["asset", "list", question.id],
        ["asset", "show", question.id, "figure"],
        [
            "asset",
            "replace",
            question.id,
            "figure",
            str(replacement),
            "--representation-id",
            "replacement",
            "--format",
            "json",
        ],
        ["asset", "set-render", question.id, "figure", "original", "--format", "json"],
        ["asset", "set-editor", question.id, "tikz", "tikz-source", "--format", "json"],
        ["asset", "open", question.id, "figure", "--dry-run", "--format", "json"],
        ["asset", "edit", question.id, "tikz", "--dry-run", "--format", "json"],
        ["asset", "finalize", question.id, "figure", "--format", "json"],
        ["asset", "normalize", question.id, "--asset-id", "figure", "--format", "json"],
        ["asset", "validate", "--format", "json"],
    ]
    for arguments in invocations:
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0, (arguments, result.stdout)

    normalized = ProjectContext.from_root(cli_project).config
    record = (
        create_project_services(_context(cli_project, normalized))
        .repository.scan()
        .locate(question.id)
    )
    assert record.question.assets == ["asset:figure"]


def test_asset_render_command_uses_registered_ipe_with_test_renderer(
    project: tuple[Path, Any],
    question: Question,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    source = root / "incoming"
    source.mkdir()
    (source / "figure.ipe").write_text("<ipe/>", encoding="utf-8")
    renderer = _FakeRenderer()
    service = _fake_service(root, config, renderer)
    service.ingest_package(
        _package(
            question.id,
            "ipe",
            [
                AssetPackageRepresentation(
                    representation_id="ipe-source",
                    format=AssetFormat.IPE,
                    path="figure.ipe",
                    purpose="source",
                    editable=True,
                )
            ],
            editor="ipe-source",
        ),
        source,
        dry_run=False,
    )
    monkeypatch.setattr(
        asset_commands, "_services_for_question", lambda _: type("S", (), {"assets": service})()
    )
    monkeypatch.chdir(root)

    result = runner.invoke(
        app,
        [
            "asset",
            "render",
            question.id,
            "ipe",
            "--render-format",
            "svg",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["action"] == "render"
    assert renderer.calls == [
        (root / "assets" / question.id / "ipe" / "ipe-source.ipe", (AssetFormat.SVG,), False)
    ]


def test_ipe_adapter_discovers_configured_tools_and_renders_with_safe_subprocess(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    bin_dir = root / "ipe-bin"
    bin_dir.mkdir()
    executables = {
        name: bin_dir / name for name in ("ipe.exe", "iperender.exe", "ipetoipe.exe", "editor.exe")
    }
    for path in executables.values():
        path.write_bytes(b"test executable")
    source = root / "source.ipe"
    source.write_text("<ipe/>", encoding="utf-8")
    configured = config.model_copy(deep=True)
    configured.assets.editors.ipe.command = str(executables["ipe.exe"])
    configured.assets.editors.text.command = str(executables["editor.exe"])
    configured.assets.renderers.ipe.iperender = str(executables["iperender.exe"])
    configured.assets.renderers.ipe.ipetoipe = str(executables["ipetoipe.exe"])
    context = _context(root, configured)

    toolchain = IpeToolchain.discover(context)
    adapter = IpeRenderAdapter(context)
    preview = adapter.render(
        source, (AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG), execute=False
    )
    assert toolchain.ipe == executables["ipe.exe"]
    assert [item.format for item in preview] == [AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG]

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        Path(command[-1]).write_bytes(b"rendered")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(ipe_infrastructure.subprocess, "run", fake_run)
    rendered = adapter.render(
        source, (AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG), execute=True
    )
    assert [item.content for item in rendered] == [b"rendered", b"rendered", b"rendered"]

    launcher = SafeAssetLauncher(context)
    assert launcher.open_file(source, execute=False)[0] == "system-default"
    assert (
        launcher.open_url("https://example.invalid/diagram.svg", execute=False)[0]
        == "system-browser"
    )
    assert launcher.open_directory(root, execute=False)[0] == "system-default"
    assert launcher.edit_file(source, AssetFormat.IPE, execute=False)[0] == str(
        executables["ipe.exe"]
    )
    assert launcher.edit_file(source, AssetFormat.TIKZ, execute=False)[0] == str(
        executables["editor.exe"]
    )


def test_ipe_adapter_rejects_unsupported_and_missing_render_output(
    project: tuple[Path, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, config = project
    bin_dir = root / "ipe-bin"
    bin_dir.mkdir()
    for name in ("ipe.exe", "iperender.exe", "ipetoipe.exe"):
        (bin_dir / name).write_bytes(b"test executable")
    source = root / "source.ipe"
    source.write_text("<ipe/>", encoding="utf-8")
    configured = config.model_copy(deep=True)
    configured.assets.editors.ipe.command = str(bin_dir / "ipe.exe")
    configured.assets.renderers.ipe.iperender = str(bin_dir / "iperender.exe")
    configured.assets.renderers.ipe.ipetoipe = str(bin_dir / "ipetoipe.exe")
    adapter = IpeRenderAdapter(_context(root, configured))

    with pytest.raises(AssetCommandError, match="asset_command_failed"):
        adapter.render(source, (AssetFormat.TIKZ,), execute=False)

    monkeypatch.setattr(
        ipe_infrastructure.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
    )
    with pytest.raises(AssetCommandError, match="did not create"):
        adapter.render(source, (AssetFormat.SVG,), execute=True)


def test_local_server_dispatches_only_registered_actions_and_rejects_bad_http(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    context = _context(root, config)
    services = create_project_services(context)
    package = _package(
        question.id,
        "managed",
        [
            AssetPackageRepresentation(
                representation_id="original",
                format=AssetFormat.PNG,
                base64=base64.b64encode(b"original").decode("ascii"),
                purpose="original",
            ),
            AssetPackageRepresentation(
                representation_id="tikz-source",
                format=AssetFormat.TIKZ,
                inline_tikz="\\begin{tikzpicture}\\end{tikzpicture}",
                purpose="source",
                editable=True,
            ),
        ],
        editor="tikz-source",
        render="original",
    )
    services.assets.ingest_package(package, root, dry_run=False)
    server, endpoint = create_asset_management_server(
        context,
        services.assets,
        services.renderer,
        questions=0,
        port=0,
    )
    manager = server.manager
    assert manager.dispatch(
        question.id, "managed", "set-render", {"representation_id": "original"}
    ).ok
    assert manager.dispatch(
        question.id, "managed", "set-editor", {"representation_id": "tikz-source"}
    ).ok
    replaced = manager.dispatch(
        question.id,
        "managed",
        "replace",
        {"data_uri": "data:image/png;base64,eA==", "format": "png", "representation_id": "web"},
    )
    assert replaced.action == "replace"
    with pytest.raises(DataValidationError, match="unsupported action"):
        manager.dispatch(question.id, "managed", "shell", {})

    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for suffix in ("preview/missing.html", "_assets/too/few"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"{endpoint.url}{suffix}", timeout=5)
            assert error.value.code == 404
        invalid = urllib.request.Request(
            f"{endpoint.url}api/assets/{question.id}/managed/finalize",
            data=b"not-json",
            method="POST",
            headers={"Content-Type": "application/json", "X-QBank-Token": manager.token},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(invalid, timeout=5)
        assert error.value.code == 400
        cross_origin = urllib.request.Request(
            f"{endpoint.url}api/assets/{question.id}/managed/finalize",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Origin": "http://example.invalid",
                "X-QBank-Token": manager.token,
            },
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(cross_origin, timeout=5)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_asset_models_reject_inconsistent_sources_preferences_and_derivations() -> None:
    """Keep all model-side asset invariants independently regression-tested."""

    valid = {
        "representation_id": "source",
        "format": AssetFormat.PNG,
        "path": "source.png",
        "purpose": "original",
        "content_hash": "0" * 64,
    }
    for values in (
        {**valid, "url": "https://example.invalid/source.png"},
        {**valid, "content_hash": None},
        {**valid, "path": None, "url": "ftp://example.invalid/source.png"},
    ):
        with pytest.raises(ValidationError):
            AssetRepresentation.model_validate(values)

    first = AssetRepresentation.model_validate(valid)
    editable = AssetRepresentation.model_validate(
        {**valid, "representation_id": "editable", "path": "editable.png", "editable": True}
    )
    for values in (
        {"representations": [first, first]},
        {"representations": [first], "preferred_editor": "source"},
        {"representations": [first], "preferred_render": "missing"},
        {
            "representations": [
                AssetRepresentation.model_validate({**valid, "derived_from": "missing"})
            ]
        },
        {
            "representations": [
                AssetRepresentation.model_validate({**valid, "derived_from": "source"})
            ]
        },
        {
            "representations": [
                AssetRepresentation.model_validate(
                    {**valid, "representation_id": "one", "path": "one.png", "derived_from": "two"}
                ),
                AssetRepresentation.model_validate(
                    {**valid, "representation_id": "two", "path": "two.png", "derived_from": "one"}
                ),
            ]
        },
    ):
        with pytest.raises(ValidationError):
            AssetManifest.model_validate(
                {
                    "schema_version": "1.0",
                    "question_id": "OPT-INT-0001",
                    "asset_id": "figure",
                    "role": "diagram",
                    "status": "raw",
                    **values,
                }
            )
    assert (
        AssetManifest.model_validate(
            {
                "schema_version": "1.0",
                "question_id": "OPT-INT-0001",
                "asset_id": "figure",
                "role": "diagram",
                "status": "raw",
                "preferred_editor": "editable",
                "preferred_render": "source",
                "representations": [first, editable],
            }
        ).asset_id
        == "figure"
    )

    package_base = {
        "schema_version": "1.0",
        "question_id": "OPT-INT-0001",
        "asset_id": "package",
        "role": "diagram",
    }
    for representation in (
        {
            "representation_id": "bad",
            "format": "png",
            "purpose": "x",
            "base64": "eA==",
            "url": "https://example.invalid/x.png",
        },
        {"representation_id": "bad", "format": "tikz", "purpose": "x", "inline_tikz": "   "},
        {"representation_id": "bad", "format": "png", "purpose": "x", "data_uri": "not-data"},
        {"representation_id": "bad", "format": "png", "purpose": "x", "base64": "%%%"},
    ):
        with pytest.raises(ValidationError):
            AssetPackageRepresentation.model_validate(representation)
    source_package = AssetPackageRepresentation(
        representation_id="source", format=AssetFormat.PNG, base64="eA==", purpose="original"
    )
    for values in (
        {"representations": [source_package, source_package]},
        {"representations": [source_package], "suggested_editor": "source"},
        {"representations": [source_package], "suggested_render": "missing"},
        {"representations": [source_package.model_copy(update={"derived_from": "missing"})]},
    ):
        with pytest.raises(ValidationError):
            AssetPackage.model_validate({**package_base, **values})


def test_asset_service_rejects_invalid_preferences_missing_files_and_targets(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    service = _services(root, config)
    service.ingest_package(_png_package(question.id), root, dry_run=False)
    with pytest.raises(DataValidationError, match="not editable"):
        service.set_preference(question.id, "figure", "original", kind="editor", dry_run=False)

    ipe = _package(
        question.id,
        "source-only",
        [
            AssetPackageRepresentation(
                representation_id="ipe-source",
                format=AssetFormat.IPE,
                base64="eA==",
                purpose="source",
                editable=True,
            )
        ],
        editor="ipe-source",
    )
    service.ingest_package(ipe, root, dry_run=False)
    with pytest.raises(DataValidationError, match="not renderable"):
        service.set_preference(
            question.id, "source-only", "ipe-source", kind="render", dry_run=False
        )
    source_manifest = service.show_asset(question.id, "source-only").asset
    with pytest.raises(DataValidationError, match="no compatible representation"):
        service.select(source_manifest, "html")

    figure = service.show_asset(question.id, "figure").asset
    local_file = service.repository.representation_path(figure, "original")
    assert local_file is not None
    local_file.unlink()
    with pytest.raises(DataValidationError, match="preferred render does not exist"):
        service.finalize(question.id, "figure", dry_run=False)


def test_asset_normalize_is_a_noop_without_legacy_references(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    context = _context(root, config)
    add_question(root, config, question)
    services = create_project_services(context)

    result = normalize_asset_references_in_context(
        context,
        question.id,
        assets=services.assets,
        mutations=services.mutations,
        dry_run=True,
    )

    assert not result.changed
    assert result.assets == []


def test_asset_normalize_replaces_a_declared_markdown_placeholder(
    project: tuple[Path, Any],
    question: Question,
) -> None:
    root, config = project
    context = _context(root, config)
    placeholder_question = question.model_copy(update={"stem_md": "请看 [drawing]", "assets": []})
    add_question(root, config, placeholder_question)
    services = create_project_services(context)
    package = _png_package(question.id).model_copy(
        update={
            "provenance": {
                "markdown_placeholder": "[drawing]",
                "content_field": "stem_md",
                "alt": "示意图",
            }
        }
    )
    services.assets.ingest_package(package, root, dry_run=False)

    result = normalize_asset_references_in_context(
        context,
        question.id,
        assets=services.assets,
        mutations=services.mutations,
        dry_run=True,
    )

    assert result.changed
    assert {change.field for change in result.changes} == {"assets", "stem_md"}
