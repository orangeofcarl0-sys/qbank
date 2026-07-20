"""Typed adapters around ruamel.yaml's intentionally dynamic API."""

from __future__ import annotations

import io
from typing import Protocol, TextIO, cast

from ruamel.yaml import YAML


class _YamlLoader(Protocol):
    def load(self, stream: str) -> object: ...


class _YamlDumper(Protocol):
    default_flow_style: bool
    allow_unicode: bool

    def indent(self, *, mapping: int, sequence: int, offset: int) -> None: ...

    def dump(self, data: object, stream: TextIO) -> None: ...


def load_yaml(text: str) -> object:
    """Load YAML while containing third-party dynamic typing at this boundary."""
    loader = cast(_YamlLoader, YAML(typ="safe"))
    return loader.load(text)


def dump_yaml(data: object) -> str:
    """Dump a YAML object using the project's stable indentation rules."""
    dumper = cast(_YamlDumper, YAML())
    dumper.default_flow_style = False
    dumper.allow_unicode = True
    dumper.indent(mapping=2, sequence=4, offset=2)
    stream = io.StringIO()
    dumper.dump(data, stream)
    return stream.getvalue().rstrip()
