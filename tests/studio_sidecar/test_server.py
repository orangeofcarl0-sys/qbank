from __future__ import annotations

import io
import json

import pytest

from qbank.studio_sidecar.server import run_server


def test_server_reserves_stdout_for_protocol() -> None:
    stdin = io.StringIO(
        "\n".join(
            [
                '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
                '{"jsonrpc":"2.0","id":2,"method":"application.shutdown","params":{}}',
            ]
        )
        + "\n"
    )
    stdout = io.StringIO()
    assert run_server(stdin, stdout) == 0
    lines = stdout.getvalue().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["id"] for line in lines] == [1, 2]
    assert all(json.loads(line)["jsonrpc"] == "2.0" for line in lines)


def test_server_returns_parse_error_and_continues() -> None:
    stdin = io.StringIO('{\n{"jsonrpc":"2.0","id":2,"method":"application.shutdown","params":{}}\n')
    stdout = io.StringIO()
    run_server(stdin, stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["result"]["ok"] is True


def test_server_converts_unhandled_boundary_failure_to_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "qbank.studio_sidecar.server.StudioApplication.dispatch",
        lambda _self, _method, _params: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    stdin = io.StringIO('{"jsonrpc":"2.0","id":8,"method":"initialize"}\n')
    stdout = io.StringIO()
    run_server(stdin, stdout)
    response = json.loads(stdout.getvalue())
    assert response["id"] == 8
    assert response["error"]["code"] == -32000
    assert response["error"]["message"] == "boom"
