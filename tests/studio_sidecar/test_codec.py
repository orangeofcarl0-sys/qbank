from __future__ import annotations

import json

import pytest

from qbank.studio_sidecar.codec import decode_request, failure, success
from qbank.studio_sidecar.errors import INVALID_REQUEST, PARSE_ERROR, RpcError


def test_codec_round_trip_keeps_unicode() -> None:
    line = success(7, {"title": "中文题目"})
    assert json.loads(line) == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"title": "中文题目"},
    }
    assert "中文题目" in line


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("{", PARSE_ERROR),
        ("[]", INVALID_REQUEST),
        ('{"jsonrpc":"1.0","method":"initialize"}', INVALID_REQUEST),
        ('{"jsonrpc":"2.0","method":""}', INVALID_REQUEST),
        ('{"jsonrpc":"2.0","method":"initialize","params":[]}', INVALID_REQUEST),
    ],
)
def test_invalid_requests_are_stable(line: str, code: int) -> None:
    with pytest.raises(RpcError) as captured:
        decode_request(line)
    assert captured.value.code == code


def test_failure_serializes_optional_data() -> None:
    payload = json.loads(failure("id", RpcError(-32002, "conflict", {"actual": "b"})))
    assert payload["error"] == {
        "code": -32002,
        "message": "conflict",
        "data": {"actual": "b"},
    }
