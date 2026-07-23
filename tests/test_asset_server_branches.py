"""Local asset-management server routing and input boundaries."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from qbank.asset_server import (
    _AssetManager,
    _contained_path,
    _mime_type,
    _render_formats,
    _representation,
    _required_text,
    _uploaded_representation,
    create_asset_management_server,
)
from qbank.context import ProjectContext
from qbank.errors import DataValidationError
from qbank.models import AssetFormat, AssetManifest, AssetRepresentation, AssetStatus


class _Result(BaseModel):
    ok: bool = True


def _manifest(representation: AssetRepresentation) -> AssetManifest:
    return AssetManifest(
        schema_version="1.0",
        question_id="Q-SERVER-1",
        asset_id="figure",
        role="figure",
        status=AssetStatus.RAW,
        preferred_render=representation.representation_id,
        representations=[representation],
    )


def _local(path: str = "image.png") -> AssetRepresentation:
    return AssetRepresentation(
        representation_id="image",
        format=AssetFormat.PNG,
        path=path,
        purpose="original",
        content_hash="0" * 64,
    )


def test_asset_manager_dispatches_every_allowlisted_action(project: tuple[Path, Any]) -> None:
    root, _ = project
    calls: list[tuple[str, object]] = []
    result = _Result()
    assets = SimpleNamespace(
        open_asset=lambda *_args, **_kwargs: calls.append(("open", None)) or result,
        edit_asset=lambda *_args, **_kwargs: calls.append(("edit", None)) or result,
        open_asset_directory=lambda *_args, **_kwargs: calls.append(("directory", None)) or result,
        render_asset=lambda *_args, **kwargs: calls.append(("render", kwargs["formats"])) or result,
        set_preference=lambda *_args, **kwargs: (
            calls.append(("preference", kwargs["kind"])) or result
        ),
        finalize=lambda *_args, **_kwargs: calls.append(("finalize", None)) or result,
        replace=lambda *_args, **_kwargs: calls.append(("replace", None)) or result,
        repository=SimpleNamespace(list=lambda **_kwargs: ()),
    )
    manager = _AssetManager(ProjectContext.from_root(root), assets, SimpleNamespace(), questions=0)
    for action, payload in (
        ("open", {}),
        ("edit", {}),
        ("open-directory", {}),
        ("render", {"formats": ["svg"]}),
        ("set-render", {"representation_id": "image"}),
        ("set-editor", {"representation_id": "source"}),
        ("finalize", {}),
        (
            "replace",
            {"data_uri": "data:image/png;base64,eA==", "format": "png"},
        ),
    ):
        assert manager.dispatch("Q-SERVER-1", "figure", action, payload).ok
    assert [item[0] for item in calls] == [
        "open",
        "edit",
        "directory",
        "render",
        "preference",
        "preference",
        "finalize",
        "replace",
    ]


def test_registered_file_rejects_remote_missing_and_escape(
    project: tuple[Path, Any], tmp_path: Path
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    remote = AssetRepresentation(
        representation_id="remote",
        format=AssetFormat.PNG,
        url="https://example.com/image.png",
        purpose="reference",
    )
    repository = SimpleNamespace(
        get=lambda *_args: _manifest(remote),
        representation_path=lambda *_args: None,
        list=lambda **_kwargs: (),
    )
    assets = SimpleNamespace(repository=repository)
    manager = _AssetManager(context, assets, SimpleNamespace(), questions=0)
    with pytest.raises(DataValidationError, match="remote"):
        manager.registered_file("Q-SERVER-1", "figure", "remote")

    repository.get = lambda *_args: _manifest(_local())
    with pytest.raises(DataValidationError, match="does not exist"):
        manager.registered_file("Q-SERVER-1", "figure", "image")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    repository.representation_path = lambda *_args: outside
    with pytest.raises(DataValidationError, match="escaped assets root"):
        manager.registered_file("Q-SERVER-1", "figure", "image")
    inside = context.paths.assets / "Q-SERVER-1" / "figure" / "image.png"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"inside")
    repository.representation_path = lambda *_args: inside
    assert manager.registered_file("Q-SERVER-1", "figure", "image") == inside


def test_server_payload_format_and_path_helpers(project: tuple[Path, Any]) -> None:
    root, _ = project
    assert _render_formats(None) == (AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG)
    assert _render_formats(["png"]) == (AssetFormat.PNG,)
    for value in ([], "png", [1]):
        with pytest.raises(DataValidationError, match="formats"):
            _render_formats(value)
    with pytest.raises(DataValidationError, match="unsupported render format"):
        _render_formats(["unsupported"])
    with pytest.raises(DataValidationError, match="is required"):
        _required_text({}, "format")
    with pytest.raises(DataValidationError, match="is required"):
        _required_text({"format": 3}, "format")
    assert _required_text({"format": " png "}, "format") == "png"

    uploaded = _uploaded_representation(
        {"data_uri": "data:image/png;base64,eA==", "format": "png", "editable": 1}
    )
    assert uploaded.representation_id == "replacement" and uploaded.editable
    with pytest.raises(ValueError):
        _uploaded_representation({"data_uri": "data:image/png;base64,eA==", "format": "bad"})

    preview = ProjectContext.from_root(root).paths.build / "preview"
    assert _contained_path(preview, "nested/index.html") == preview / "nested" / "index.html"
    with pytest.raises(DataValidationError, match="escapes"):
        _contained_path(preview, "../outside.html")
    assert _mime_type(Path("image.svg")) == "image/svg+xml"
    assert _mime_type(Path("unknown.qbank-extension")) == "application/octet-stream"
    with pytest.raises(DataValidationError, match="representation_missing"):
        _representation([_local()], "missing")

    with pytest.raises(DataValidationError, match="port"):
        create_asset_management_server(
            ProjectContext.from_root(root),
            SimpleNamespace(repository=SimpleNamespace(list=lambda **_kwargs: ())),
            SimpleNamespace(),
            questions=0,
            port=70000,
        )
