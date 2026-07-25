"""JSON-RPC 2.0 line codec with deterministic response shapes."""

from __future__ import annotations

import json
from typing import Any, cast

from qbank.studio_sidecar.errors import INVALID_REQUEST, PARSE_ERROR, RpcError


def decode_request(line: str) -> tuple[int | str | None, str, dict[str, Any]]:
    try:
        value = cast(object, json.loads(line))
    except json.JSONDecodeError as exc:
        raise RpcError(PARSE_ERROR, "invalid JSON", {"offset": exc.pos}) from exc
    if not isinstance(value, dict):
        raise RpcError(INVALID_REQUEST, "request must be a JSON-RPC 2.0 object")
    request = cast(dict[str, object], value)
    if request.get("jsonrpc") != "2.0":
        raise RpcError(INVALID_REQUEST, "request must be a JSON-RPC 2.0 object")
    identifier = request.get("id")
    if identifier is not None and not isinstance(identifier, int | str):
        raise RpcError(INVALID_REQUEST, "request id must be a string, integer, or null")
    method = request.get("method")
    if not isinstance(method, str) or not method:
        raise RpcError(INVALID_REQUEST, "request method must be a non-empty string")
    params = request.get("params", {})
    if not isinstance(params, dict):
        raise RpcError(INVALID_REQUEST, "request params must be an object")
    return identifier, method, cast(dict[str, Any], params)


def success(identifier: int | str | None, result: Any) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "result": result},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def failure(identifier: int | str | None, error: RpcError) -> str:
    payload: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data is not None:
        payload["data"] = error.data
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "error": payload},
        ensure_ascii=False,
        separators=(",", ":"),
    )
