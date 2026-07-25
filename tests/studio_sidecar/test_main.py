from __future__ import annotations

import io
import sys

import pytest

from qbank.studio_sidecar import __main__


class ReconfigurableText(io.StringIO):
    def reconfigure(self, **_kwargs: object) -> None:
        pass


def test_main_reserves_original_stdout_for_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdin = ReconfigurableText()
    stdout = ReconfigurableText()
    stderr = ReconfigurableText()
    captured: dict[str, object] = {}

    def fake_server(server_stdin: object, protocol_stdout: object) -> int:
        captured.update(stdin=server_stdin, stdout=protocol_stdout)
        return 7

    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr("qbank.studio_sidecar.server.run_server", fake_server)
    with pytest.raises(SystemExit) as captured_exit:
        __main__.main()
    assert captured_exit.value.code == 7
    assert captured == {"stdin": stdin, "stdout": stdout}
    assert sys.stdout is stderr
