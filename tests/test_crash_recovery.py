"""Durable file-transaction recovery after abrupt child-process exits."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from qbank.context import ProjectContext
from qbank.infrastructure.locking import RepositoryWriteLock


def _crash_script(root: Path, point: str) -> str:
    return f"""
import os
from pathlib import Path
import qbank.transaction as module
from qbank.context import ProjectContext

root = Path({str(root)!r})
context = ProjectContext.from_root(root)
one = root / 'questions' / 'one.txt'
two = root / 'questions' / 'two.txt'
transaction = module.MutationTransaction.for_context(context)
transaction.write(one, 'after-one')
transaction.write(two, 'after-two')
original_write = module.atomic_write_text
original_remove = module._remove_journal

def crash_write(path, text):
    if path == one:
        if {point!r} == 'before-authority':
            os._exit(81)
        original_write(path, text)
        os._exit(82)
    original_write(path, text)

def crash_cleanup(journal):
    os._exit(83)

if {point!r} in ('before-authority', 'during-replace'):
    module.atomic_write_text = crash_write
elif {point!r} == 'after-commit-marker':
    module._remove_journal = crash_cleanup
transaction.commit()
"""


@pytest.mark.parametrize(
    ("point", "exit_code", "first_after_crash"),
    (("before-authority", 81, "before-one"), ("during-replace", 82, "after-one")),
)
def test_prepared_transaction_is_rolled_back_after_process_exit(
    project: tuple[Path, object],
    point: str,
    exit_code: int,
    first_after_crash: str,
) -> None:
    root, _ = project
    one = root / "questions" / "one.txt"
    two = root / "questions" / "two.txt"
    one.write_text("before-one", encoding="utf-8")
    two.write_text("before-two", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", _crash_script(root, point)],
        cwd=root,
        check=False,
    )
    assert result.returncode == exit_code
    assert one.read_text(encoding="utf-8") == first_after_crash
    assert two.read_text(encoding="utf-8") == "before-two"

    with RepositoryWriteLock(ProjectContext.from_root(root)).hold("recover-test"):
        pass

    assert one.read_text(encoding="utf-8") == "before-one"
    assert two.read_text(encoding="utf-8") == "before-two"
    assert not list((root / ".qbank" / "transactions").glob("*.txn"))


def test_committed_transaction_is_kept_when_cleanup_process_exits(
    project: tuple[Path, object],
) -> None:
    root, _ = project
    one = root / "questions" / "one.txt"
    two = root / "questions" / "two.txt"
    one.write_text("before-one", encoding="utf-8")
    two.write_text("before-two", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", _crash_script(root, "after-commit-marker")],
        cwd=root,
        check=False,
    )
    assert result.returncode == 83
    assert one.read_text(encoding="utf-8") == "after-one"
    assert two.read_text(encoding="utf-8") == "after-two"

    with RepositoryWriteLock(ProjectContext.from_root(root)).hold("recover-committed"):
        pass

    assert one.read_text(encoding="utf-8") == "after-one"
    assert two.read_text(encoding="utf-8") == "after-two"
    assert not list((root / ".qbank" / "transactions").glob("*.txn"))
