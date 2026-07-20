"""Shared qbank test fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from qbank.models import Question
from qbank.project import initialize_project, load_config


@pytest.fixture
def runner() -> CliRunner:
    """Return an isolated Typer runner."""
    return CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Any]:
    """Create a fresh initialized question bank."""
    initialize_project(tmp_path)
    return tmp_path, load_config(tmp_path)


@pytest.fixture
def cli_project(project: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change into a fresh project for CLI tests."""
    root, _ = project
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def question_data() -> dict[str, Any]:
    """Return one complete, valid exchange object."""
    return {
        "schema_version": "1.0",
        "id": "OPT-INT-0001",
        "title": "Michelson 光程差",
        "type": "calculation",
        "subject": "optics",
        "chapter": "interferometry",
        "topics": ["interferometry", "optical-path-difference"],
        "difficulty": 2,
        "status": "reviewed",
        "language": "zh-CN",
        "source": {"type": "manual", "reference": None},
        "assets": [],
        "stem_md": "反射镜移动 $1.5\\,\\mathrm{mm}$，求光程差。",
        "options_md": "",
        "answer_md": "$3.0\\,\\mathrm{mm}$",
        "solution_md": "$\\Delta L=2\\Delta x$。",
        "rubric_md": "- 往返因子 2",
        "review_notes_md": "",
    }


@pytest.fixture
def question(question_data: dict[str, Any]) -> Question:
    """Return the validated sample question."""
    return Question.model_validate(question_data)


@pytest.fixture
def make_question(question_data: dict[str, Any]):
    """Return a factory that validates updated sample values."""

    def factory(**updates: Any) -> Question:
        data = {**question_data, **updates}
        return Question.model_validate(data)

    return factory


@pytest.fixture
def imported_project(
    project: tuple[Path, Any],
    make_question: Any,
) -> tuple[Path, Any]:
    """Create a project containing the five demo-paper questions."""
    from qbank.operations import add_question

    root, config = project
    questions = [
        make_question(),
        make_question(
            id="OPT-DIF-0001",
            title="衍射选择",
            type="single_choice",
            chapter="diffraction",
            topics=["diffraction"],
            options_md="- A. 增大\n- B. 减小",
            answer_md="A",
        ),
        make_question(
            id="ELEC-AMP-0001",
            title="运放",
            type="multiple_choice",
            subject="electronics",
            chapter="amplifiers",
            topics=["op-amp"],
            options_md="- A. 虚短\n- B. 虚断\n- C. 饱和",
            answer_md="A, B",
        ),
        make_question(
            id="MATH-CALC-0001",
            title="导数",
            type="fill_blank",
            subject="mathematics",
            chapter="calculus",
            topics=["derivative"],
            answer_md="$2x$",
        ),
        make_question(
            id="SIG-FFT-0001",
            title="FFT",
            type="true_false",
            subject="signals",
            chapter="fourier-analysis",
            topics=["fft"],
            options_md="- 正确\n- 错误",
            answer_md="正确",
        ),
    ]
    for item in questions:
        add_question(root, config, item)
    return root, config
