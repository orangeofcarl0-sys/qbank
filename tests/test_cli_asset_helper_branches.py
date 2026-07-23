"""CLI asset source parsing and validation edge cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from qbank.commands.assets import (
    _asset_format,
    _default_representation_id,
    _existing_source_path,
    _format_from_name,
    _format_from_source,
    _inline_source,
    _pdf_metadata,
    _render_formats,
    _safe_id,
    _source_representation,
    _source_stem,
)
from qbank.errors import DataValidationError
from qbank.models import AssetFormat


def test_source_representation_accepts_each_supported_input_shape(tmp_path: Path) -> None:
    local = tmp_path / "source.svg"
    local.write_text("<svg/>", encoding="utf-8")
    representation, root, label = _source_representation(
        str(local),
        representation_id=None,
        source_format=None,
        purpose="original",
        editable=False,
        metadata={},
    )
    assert (representation.format, root, label) == (AssetFormat.SVG, tmp_path, str(local.resolve()))

    for source, expected_format, expected_label in (
        ("https://example.com/a.png", AssetFormat.PNG, "https://example.com/a.png"),
        ("data:image/png;base64,eA==", AssetFormat.PNG, "data-uri"),
        (r"\begin{tikzpicture}\end{tikzpicture}", AssetFormat.TIKZ, "inline-tikz"),
        ("eA==", AssetFormat.PNG, "base64"),
    ):
        item, _, source_label = _source_representation(
            source,
            representation_id="input",
            source_format="png" if source == "eA==" else None,
            purpose="replacement",
            editable=False,
            metadata={"source": "test"},
        )
        assert item.format == expected_format
        assert source_label == expected_label


def test_asset_format_and_source_helpers_cover_rejections() -> None:
    assert _render_formats(None) == (AssetFormat.PDF, AssetFormat.SVG, AssetFormat.PNG)
    with pytest.raises(DataValidationError, match="render formats"):
        _render_formats(["ipe"])
    with pytest.raises(DataValidationError, match="unsupported asset format"):
        _asset_format("unknown")

    assert _format_from_source("data:application/pdf;base64,eA==") == AssetFormat.PDF
    assert _format_from_source("data:application/octet-stream;base64,eA==") == AssetFormat.OTHER
    assert _format_from_source("https://example.com/no-extension") == AssetFormat.URL
    assert _format_from_source("https://example.com/image.jpeg") == AssetFormat.JPEG
    assert _format_from_source(r"\begin{tikzpicture}") == AssetFormat.TIKZ
    assert _format_from_source("opaque") == AssetFormat.OTHER
    with pytest.raises(DataValidationError, match="unsupported asset file"):
        _format_from_name("figure.unknown")

    assert _default_representation_id(AssetFormat.IPE) == "ipe-source"
    assert _default_representation_id(AssetFormat.TIKZ) == "tikz-source"
    assert _default_representation_id(AssetFormat.PNG) == "original"
    assert _source_stem("https://example.com/") == "remote"
    assert _source_stem("https://example.com/figure.png") == "figure"
    assert _source_stem("folder/figure.svg") == "figure"
    assert _source_stem("inline content").startswith("asset-")
    assert _existing_source_path("data:image/png;base64,eA==") is None
    assert _inline_source("http://example.com/a")
    assert _inline_source(r"\begin{tikzpicture}")


def test_asset_ids_and_pdf_metadata_are_strict() -> None:
    assert _safe_id(" figure one ", "fallback") == "figure-one"
    assert _safe_id("***", "fallback") == "fallback"
    with pytest.raises(DataValidationError, match="unsafe asset ID"):
        _safe_id("***", "also unsafe")

    assert _pdf_metadata(None, None) == {}
    assert _pdf_metadata(2, "0, 1, 4, 5") == {"page": 2, "crop": [0.0, 1.0, 4.0, 5.0]}
    with pytest.raises(DataValidationError, match="page"):
        _pdf_metadata(0, None)
    with pytest.raises(DataValidationError, match="crop"):
        _pdf_metadata(None, "not,numbers")
    for crop in ("0,1,2", "2,1,0,5", "0,5,2,1"):
        with pytest.raises(DataValidationError, match="crop"):
            _pdf_metadata(None, crop)
