"""Filesystem asset adapter failure and normalization branches."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from qbank.context import ProjectContext
from qbank.domain import AssetHistoryEvent
from qbank.errors import AssetConflictError, AssetNotFoundError, DataValidationError
from qbank.infrastructure.assets import (
    AssetInputAdapter,
    FileAssetRepository,
    _contained_file,
    _decode_base64,
    _decode_data_uri,
    _normalized_suffix,
    _representation,
    _url_suffix,
    _validate_identifier,
)
from qbank.models import (
    AssetFormat,
    AssetManifest,
    AssetPackageRepresentation,
    AssetRepresentation,
    AssetStatus,
)


def _manifest(representation: AssetRepresentation) -> AssetManifest:
    return AssetManifest(
        schema_version="1.0",
        question_id="Q-ASSET-1",
        asset_id="figure",
        role="figure",
        status=AssetStatus.RAW,
        preferred_render=representation.representation_id,
        representations=[representation],
    )


def _local_rep(path: str = "original.png") -> AssetRepresentation:
    return AssetRepresentation(
        representation_id="original",
        format=AssetFormat.PNG,
        path=path,
        purpose="original",
        content_hash="0" * 64,
    )


def test_file_repository_reports_corruption_and_rejects_unregistered_writes(
    project: tuple[Path, Any],
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    repository = FileAssetRepository(context)
    corrupt = context.paths.assets / "Q-BAD-1" / "bad" / "asset.yaml"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("not: [valid", encoding="utf-8")
    assert repository.list(strict=False) == ()
    assert repository.diagnostics()[0].code == "asset_manifest_invalid"
    with pytest.raises(DataValidationError, match="asset_manifest_invalid"):
        repository.list()
    with pytest.raises(AssetNotFoundError):
        repository.get("Q-ASSET-1", "missing")

    remote = AssetRepresentation(
        representation_id="remote",
        format=AssetFormat.PNG,
        url="https://example.com/a.png",
        purpose="reference",
    )
    assert repository.representation_path(_manifest(remote), "remote") is None
    with pytest.raises(AssetNotFoundError):
        _representation(_manifest(remote), "missing")
    with pytest.raises(DataValidationError, match="unregistered"):
        repository.commit(
            _manifest(_local_rep()),
            {"other.png": b"content"},
            AssetHistoryEvent(
                operation="asset_create",
                question_id="Q-ASSET-1",
                asset_id="figure",
                representation_ids=("original",),
            ),
        )


def test_file_repository_detects_content_conflict_and_discards_owned_history(
    project: tuple[Path, Any],
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    repository = FileAssetRepository(context)
    manifest = _manifest(_local_rep())
    event = AssetHistoryEvent(
        operation="asset_create",
        question_id=manifest.question_id,
        asset_id=manifest.asset_id,
        representation_ids=("original",),
    )
    repository.commit(manifest, {"original.png": b"first"}, event)
    with pytest.raises(AssetConflictError, match="refusing to overwrite"):
        repository.commit(manifest, {"original.png": b"second"}, event)
    history_root = context.paths.state / "asset-history"
    (history_root / "broken.json").write_text("{", encoding="utf-8")
    repository.discard_new(manifest.question_id, manifest.asset_id)
    assert not repository.location(manifest.question_id, manifest.asset_id).directory.exists()
    assert (history_root / "broken.json").exists()
    repository.discard_new("Q-NONE-1", "missing")


def test_asset_input_adapter_hash_and_decode_boundaries(project: tuple[Path, Any]) -> None:
    root, _ = project
    adapter = AssetInputAdapter(ProjectContext.from_root(root))
    mismatch = AssetPackageRepresentation(
        representation_id="original",
        format=AssetFormat.PNG,
        base64=base64.b64encode(b"content").decode("ascii"),
        purpose="original",
        content_hash="0" * 64,
    )
    with pytest.raises(DataValidationError, match="hash"):
        adapter.normalize(mismatch, package_root=root)

    malformed_uri = AssetPackageRepresentation.model_construct(
        representation_id="bad",
        format=AssetFormat.PNG,
        data_uri="not-a-data-uri",
        purpose="original",
        editable=False,
        metadata={},
    )
    with pytest.raises(DataValidationError, match="malformed data URI"):
        _decode_data_uri(malformed_uri)
    bad_payload = malformed_uri.model_copy(update={"data_uri": "data:image/png;base64,***"})
    with pytest.raises(DataValidationError, match="payload"):
        _decode_data_uri(bad_payload)
    plain = malformed_uri.model_copy(update={"data_uri": "data:text/plain,hello%20world"})
    assert _decode_data_uri(plain)[0] == b"hello world"
    with pytest.raises(DataValidationError, match="Base64"):
        _decode_base64("***")


def test_asset_path_identifier_and_suffix_helpers(tmp_path: Path) -> None:
    _validate_identifier("safe-id", "asset_id")
    with pytest.raises(DataValidationError, match="invalid asset_id"):
        _validate_identifier("../bad", "asset_id")
    with pytest.raises(DataValidationError, match="invalid representation path"):
        _contained_file(tmp_path, "../escape.png")
    with pytest.raises(DataValidationError, match="invalid representation path"):
        _contained_file(tmp_path, "/absolute.png")
    assert _contained_file(tmp_path, "nested/image.png") == tmp_path / "nested" / "image.png"
    assert _normalized_suffix(".JPEG", AssetFormat.JPEG) == ".jpeg"
    assert _normalized_suffix(".odd", AssetFormat.PNG) == ".png"
    assert _normalized_suffix("", AssetFormat.OTHER) == ".bin"
    assert _url_suffix("https://example.com/path/image.SVG?x=1") == ".svg"
