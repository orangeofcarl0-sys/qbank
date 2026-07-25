from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from qbank.bootstrap import create_project_services
from qbank.context import ProjectContext


@pytest.fixture()
def synthetic_bank(tmp_path: Path) -> Path:
    source = Path(__file__).parents[2] / "apps" / "studio" / "fixtures" / "synthetic-bank"
    target = tmp_path / "含 空格的合成题库"
    shutil.copytree(source, target)
    context = ProjectContext.from_root(target)
    create_project_services(context).questions.rebuild_index()
    return target
