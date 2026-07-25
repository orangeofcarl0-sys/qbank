"""Stable JSON-RPC error mapping for sidecar application failures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RpcError(Exception):
    code: int
    message: str
    data: dict[str, Any] | None = None


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
APPLICATION_ERROR = -32000
REPOSITORY_NOT_OPEN = -32001
CONFLICT = -32002
LOCKED = -32003
VALIDATION = -32004
