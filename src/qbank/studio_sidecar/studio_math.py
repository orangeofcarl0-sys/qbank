"""Studio math macro configuration loading for the Tauri sidecar."""

from __future__ import annotations

import json
import re
from typing import cast

from qbank.context import ProjectContext
from qbank.utils import is_reparse_point

_MACRO_NAME = re.compile(r"^[A-Za-z@]+$")
_MACRO_REFERENCE = re.compile(r"\\([A-Za-z@]+)")
_MAX_CONFIG_BYTES = 64 * 1024
_MAX_MACRO_TEXT = 1024
_MAX_MACRO_ARITY = 9
_MAX_MACRO_CHAIN = 32

StudioMacros = dict[str, str | list[str | int]]


def load_studio_math(
    context: ProjectContext,
) -> tuple[StudioMacros, list[str]]:
    """Load the repository-scoped studio-math.json macro configuration.

    Returns the validated macro table and a list of non-fatal warnings; an
    absent configuration is not a warning.
    """
    path = context.paths.state / "studio-math.json"
    if not path.exists():
        return {}, []
    if is_reparse_point(path) or not path.is_file():
        return {}, ["Studio math configuration must be a regular non-link file"]
    try:
        path.resolve(strict=True).relative_to(context.root.resolve(strict=True))
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ValueError("configuration exceeds 64 KiB")
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
        payload_object = cast(dict[str, object], payload) if isinstance(payload, dict) else {}
        macros = _parse_macros(payload_object)
        cycle = _macro_cycle(macros)
        if cycle is not None:
            raise ValueError(
                f"recursive or excessively deep macro chain: {' -> '.join(cycle)}"
            )
        return macros, []
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return {}, [f"Studio math configuration ignored: {exc}"]


def _parse_macros(payload_object: dict[str, object]) -> StudioMacros:
    values: object = payload_object.get("macros")
    if not isinstance(values, dict):
        raise ValueError("macros must be an object")
    macro_values = cast(dict[object, object], values)
    macros: StudioMacros = {}
    for name, value in macro_values.items():
        validated_name = _macro_name(name)
        macros[validated_name] = _macro_value(validated_name, value)
    return macros


def _macro_name(name: object) -> str:
    if not isinstance(name, str) or _MACRO_NAME.fullmatch(name) is None:
        raise ValueError(f"invalid macro name: {name}")
    return name


def _macro_value(name: str, value: object) -> str | list[str | int]:
    if isinstance(value, str) and len(value) <= _MAX_MACRO_TEXT:
        return value
    if isinstance(value, list) and _is_textual_pair(cast(list[object], value)):
        parts = cast(list[object], value)
        return [cast(str, parts[0]), cast(int, parts[1])]
    raise ValueError(f"invalid macro value: {name}")


def _is_textual_pair(parts: list[object]) -> bool:
    return (
        len(parts) == 2
        and isinstance(parts[0], str)
        and len(parts[0]) <= _MAX_MACRO_TEXT
        and isinstance(parts[1], int)
        and not isinstance(parts[1], bool)
        and 0 <= parts[1] <= _MAX_MACRO_ARITY
    )


def _macro_cycle(macros: StudioMacros) -> list[str] | None:
    graph = {
        name: [
            reference
            for reference in _MACRO_REFERENCE.findall(
                value if isinstance(value, str) else str(value[0])
            )
            if reference in macros
        ]
        for name, value in macros.items()
    }
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> list[str] | None:
        if name in visiting:
            index = visiting.index(name)
            return [*visiting[index:], name]
        if name in visited:
            return None
        if len(visiting) >= _MAX_MACRO_CHAIN:
            return [*visiting, name]
        visiting.append(name)
        for dependency in graph[name]:
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        visiting.pop()
        visited.add(name)
        return None

    for name in graph:
        cycle = visit(name)
        if cycle is not None:
            return cycle
    return None
