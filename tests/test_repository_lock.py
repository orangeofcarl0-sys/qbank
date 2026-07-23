"""Cross-process repository lock behavior shared by every write surface."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from qbank.context import ProjectContext
from qbank.errors import RepositoryLockedError
from qbank.infrastructure.locking import RepositoryWriteLock


def _holder_script(root: Path, *, crash: bool) -> str:
    ending = "import os; os._exit(0)" if crash else "import time; time.sleep(30)"
    return (
        "from pathlib import Path\n"
        "from qbank.context import ProjectContext\n"
        "from qbank.infrastructure.locking import RepositoryWriteLock\n"
        f"context = ProjectContext.from_root(Path({str(root)!r}))\n"
        "with RepositoryWriteLock(context).hold('child-holder'):\n"
        "    print('LOCKED', flush=True)\n"
        f"    {ending}\n"
    )


def test_repository_lock_times_out_with_holder_details(project: tuple[Path, object]) -> None:
    root, _ = project
    process = subprocess.Popen(
        [sys.executable, "-c", _holder_script(root, crash=False)],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "LOCKED"
        lock = RepositoryWriteLock(ProjectContext.from_root(root), default_timeout=0.15)
        with pytest.raises(RepositoryLockedError) as caught, lock.hold("contender"):
            pytest.fail("contender unexpectedly acquired the lock")
        assert caught.value.code.value == "repository_locked"
        assert caught.value.details["repository"] == str(root)
        holder = caught.value.details["holder"]
        assert isinstance(holder, dict)
        assert isinstance(holder["pid"], int) and holder["pid"] > 0
        assert holder["operation"] == "child-holder"
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_repository_lock_recovers_after_process_crash(project: tuple[Path, object]) -> None:
    root, _ = project
    process = subprocess.run(
        [sys.executable, "-c", _holder_script(root, crash=True)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert process.returncode == 0
    assert process.stdout.strip() == "LOCKED"
    metadata = root / ".qbank" / "repository.write-lock.json"
    stale = json.loads(metadata.read_text(encoding="utf-8"))

    lock = RepositoryWriteLock(ProjectContext.from_root(root), default_timeout=0.5)
    with lock.hold("recovery") as lease:
        assert lease.recovered_holder is not None
        assert lease.recovered_holder.pid == stale["pid"]
    assert not metadata.exists()


def test_repository_lock_is_reentrant_for_composed_services(project: tuple[Path, object]) -> None:
    root, _ = project
    lock = RepositoryWriteLock(ProjectContext.from_root(root))
    with lock.hold("outer") as outer, lock.hold("inner") as inner:
        assert inner.holder.token == outer.holder.token
    assert not (root / ".qbank" / "repository.write-lock.json").exists()
