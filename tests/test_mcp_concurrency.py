"""Interface-level concurrency coverage for the shared repository write lock."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext
from qbank.errors import RepositoryRevisionChangedError
from qbank.infrastructure.locking import RepositoryWriteLock
from qbank.mcp.adapter import QbankMcpAdapter
from qbank.models import IngestPrepareRequest, PatchPrepareRequest, Question, QuestionPatch

_INSTRUMENTED_CLI = """
from contextlib import contextmanager
import os
from pathlib import Path
from qbank.infrastructure.locking import RepositoryWriteLock

original_hold = RepositoryWriteLock.hold

@contextmanager
def notified_hold(lock, operation, *, timeout=None):
    if operation.startswith("qbank patch "):
        Path(os.environ["QBANK_TEST_LOCK_SIGNAL"]).write_text(operation, encoding="utf-8")
    with original_hold(lock, operation, timeout=timeout) as lease:
        yield lease

RepositoryWriteLock.hold = notified_hold
from qbank.cli import app
app()
"""


def _seed(adapter: QbankMcpAdapter, question: Question) -> None:
    prepared = adapter.ingest_prepare(IngestPrepareRequest(questions=[question]))
    adapter.operation_commit(prepared.operation_id, prepared.repository_revision)


def _collect(futures: tuple[Future[Any], Future[Any]]) -> tuple[list[Any], list[BaseException]]:
    results: list[Any] = []
    errors: list[BaseException] = []
    for future in futures:
        try:
            results.append(future.result(timeout=10))
        except BaseException as exc:
            errors.append(exc)
    return results, errors


def _start_cli_patch(
    root: Path,
    question_id: str,
    patch_file: Path,
    signal: Path,
) -> subprocess.Popen[str]:
    environment = dict(os.environ)
    environment["QBANK_TEST_LOCK_SIGNAL"] = str(signal)
    return subprocess.Popen(
        [
            sys.executable,
            "-c",
            _INSTRUMENTED_CLI,
            "patch",
            question_id,
            "--file",
            str(patch_file),
            "--format",
            "json",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def _wait_for_signal(process: subprocess.Popen[str], signal: Path) -> None:
    deadline = time.monotonic() + 5
    while not signal.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert signal.is_file()
    assert process.poll() is None


def _future_error(future: Future[Any]) -> BaseException | None:
    try:
        future.result(timeout=10)
    except BaseException as exc:
        return exc
    return None


def test_studio_and_mcp_concurrent_writes_share_one_lock(
    project: tuple[Path, object],
    question: Question,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    adapter = QbankMcpAdapter(context)
    _seed(adapter, question)
    prepared = adapter.patch_prepare(
        PatchPrepareRequest(
            question_id=question.id,
            patch=QuestionPatch(set={"title": "MCP winner"}),
        )
    )
    studio = create_project_services(context).studio
    reached = {
        "qbank desktop save": Event(),
        "mcp_operation_commit": Event(),
    }
    original_hold = RepositoryWriteLock.hold

    @contextmanager
    def observed_hold(
        lock: RepositoryWriteLock,
        operation: str,
        *,
        timeout: float | None = None,
    ):
        event = reached.get(operation)
        if event is not None:
            event.set()
        with original_hold(lock, operation, timeout=timeout) as lease:
            yield lease

    monkeypatch.setattr(RepositoryWriteLock, "hold", observed_hold)
    gate = RepositoryWriteLock(context)
    with ThreadPoolExecutor(max_workers=2) as executor:
        with original_hold(gate, "test_studio_mcp_gate"):
            studio_future = executor.submit(
                studio.save_question,
                question.id,
                QuestionPatch(set={"title": "Studio winner"}),
                dry_run=False,
            )
            mcp_future = executor.submit(
                adapter.operation_commit,
                prepared.operation_id,
                prepared.repository_revision,
            )
            assert reached["qbank desktop save"].wait(timeout=5)
            assert reached["mcp_operation_commit"].wait(timeout=5)
            assert not studio_future.done()
            assert not mcp_future.done()
        results, errors = _collect((studio_future, mcp_future))
    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RepositoryRevisionChangedError)
    assert adapter.question_get(question.id).title in {"Studio winner", "MCP winner"}


def test_cli_and_mcp_concurrent_writes_share_one_lock(
    project: tuple[Path, object],
    question: Question,
) -> None:
    root, _ = project
    context = ProjectContext.from_root(root)
    adapter = QbankMcpAdapter(context)
    _seed(adapter, question)
    prepared = adapter.patch_prepare(
        PatchPrepareRequest(
            question_id=question.id,
            patch=QuestionPatch(set={"title": "MCP winner"}),
        )
    )
    patch_file = root / "cli-concurrent-patch.json"
    patch_file.write_text(
        json.dumps({"set": {"title": "CLI winner"}}),
        encoding="utf-8",
    )
    signal = root / ".qbank" / "cli-lock-reached"
    process: subprocess.Popen[str] | None = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        with RepositoryWriteLock(context).hold("test_cli_mcp_gate"):
            process = _start_cli_patch(root, question.id, patch_file, signal)
            _wait_for_signal(process, signal)
            mcp_future = executor.submit(
                adapter.operation_commit,
                prepared.operation_id,
                prepared.repository_revision,
            )
            time.sleep(0.2)
            assert not mcp_future.done()
        mcp_error = _future_error(mcp_future)

    assert process is not None
    stdout, stderr = process.communicate(timeout=10)

    cli_succeeded = process.returncode == 0
    mcp_succeeded = mcp_error is None
    assert cli_succeeded != mcp_succeeded
    if not cli_succeeded:
        payload = json.loads(stdout)
        assert process.returncode == 5
        assert payload["code"] == "repository_revision_changed"
        assert stderr == ""
    if mcp_error is not None:
        assert isinstance(mcp_error, RepositoryRevisionChangedError)
    assert adapter.question_get(question.id).title in {"CLI winner", "MCP winner"}
