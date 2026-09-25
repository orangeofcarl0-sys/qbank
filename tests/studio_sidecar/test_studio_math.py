from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from qbank.context import ProjectContext
from qbank.studio_sidecar.studio_math import load_studio_math


@pytest.fixture()
def context(synthetic_bank: Path) -> Iterator[ProjectContext]:
    yield ProjectContext.from_root(synthetic_bank)


def write_config(context: ProjectContext, payload: object) -> Path:
    path = context.paths.state / "studio-math.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        path.write_text(text, encoding="utf-8")
    return path


def test_missing_configuration_is_not_a_warning(context: ProjectContext) -> None:
    assert load_studio_math(context) == ({}, [])


def test_valid_string_and_pair_macros(context: ProjectContext) -> None:
    write_config(
        context,
        {"macros": {"RR": "\\mathbb{R}", "abs": ["\\left|#1\\right|", 1]}},
    )
    macros, warnings = load_studio_math(context)
    assert macros == {"RR": "\\mathbb{R}", "abs": ["\\left|#1\\right|", 1]}
    assert warnings == []


def test_nested_macro_references_resolve(context: ProjectContext) -> None:
    write_config(context, {"macros": {"a": "\\b", "b": "\\c x", "c": "y"}})
    macros, warnings = load_studio_math(context)
    assert macros == {"a": "\\b", "b": "\\c x", "c": "y"}
    assert warnings == []


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        {},
        {"macros": "object required"},
        {"macros": {"1bad": "x"}},
        {"macros": {"RR": "x" * 1025}},
        {"macros": {"RR": ["\\left|#1\\right|", True]}},
        {"macros": {"RR": ["\\left|#1\\right|", 10]}},
        {"macros": {"RR": ["only-text"]}},
        {"macros": {"RR": 5}},
    ],
)
def test_invalid_configurations_warn_without_macros(
    context: ProjectContext, payload: object
) -> None:
    write_config(context, payload)
    macros, warnings = load_studio_math(context)
    assert macros == {}
    assert len(warnings) == 1
    assert warnings[0].startswith("Studio math configuration ignored: ")


def test_recursive_macro_chain_warns(context: ProjectContext) -> None:
    write_config(context, {"macros": {"a": "\\b", "b": "\\a"}})
    macros, warnings = load_studio_math(context)
    assert macros == {}
    assert "recursive or excessively deep macro chain" in warnings[0]


def test_oversized_configuration_warns(context: ProjectContext) -> None:
    path = write_config(context, {"macros": {"RR": "\\mathbb{R}"}})
    path.write_text('{"macros": {"RR": "' + "x" * 70_000 + '"}}', encoding="utf-8")
    macros, warnings = load_studio_math(context)
    assert macros == {}
    assert "configuration exceeds 64 KiB" in warnings[0]


def test_non_regular_file_warns(context: ProjectContext) -> None:
    path = write_config(context, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.unlink()
    path.mkdir()
    macros, warnings = load_studio_math(context)
    assert macros == {}
    assert warnings == ["Studio math configuration must be a regular non-link file"]
