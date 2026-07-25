"""Synchronous stdio server for Studio Protocol v1."""

from __future__ import annotations

import logging
from typing import TextIO

from qbank.studio_sidecar.application import StudioApplication
from qbank.studio_sidecar.codec import decode_request, failure, success
from qbank.studio_sidecar.errors import APPLICATION_ERROR, RpcError


def run_server(stdin: TextIO, stdout: TextIO) -> int:
    logging.basicConfig(
        stream=None,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    application = StudioApplication()
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        identifier: int | str | None = None
        try:
            identifier, method, params = decode_request(line)
            result = application.dispatch(method, params)
            response = success(identifier, result)
        except RpcError as exc:
            response = failure(identifier, exc)
        except Exception as exc:  # outer protocol boundary keeps stdout valid
            logging.exception("unhandled sidecar request failure")
            response = failure(identifier, RpcError(APPLICATION_ERROR, str(exc)))
        stdout.write(response + "\n")
        stdout.flush()
        if application.shutdown_requested:
            break
    return 0
