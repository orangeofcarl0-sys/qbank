"""Generate disposable qbank repositories and benchmark MCP write paths."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from qbank import __version__
from qbank.application.revision import question_projection_revision, repository_revision
from qbank.context import ProjectContext
from qbank.markdown_codec import render_question
from qbank.mcp.adapter import QbankMcpAdapter
from qbank.models import PatchPrepareRequest, Question, QuestionPatch
from qbank.project import initialize_project

DEFAULT_SCENARIOS = (
    "100:0",
    "100:100",
    "1000:0",
    "1000:100",
    "1000:1000",
    "10000:0",
    "10000:1000",
)


def _question(index: int) -> Question:
    return Question.model_validate(
        {
            "schema_version": "1.0",
            "id": f"BENCH-{index:06d}",
            "title": f"Benchmark question {index:06d}",
            "type": "short_answer",
            "subject": "benchmark",
            "chapter": "performance",
            "topics": ["benchmark"],
            "difficulty": 1 + index % 5,
            "status": "draft",
            "language": "en",
            "source": {"type": "generated"},
            "assets": [],
            "stem_md": f"Compute the deterministic benchmark value for item {index}.",
            "answer_md": str(index),
        }
    )


def _create_fixture(root: Path, question_count: int, asset_count: int) -> ProjectContext:
    initialize_project(root)
    question_directory = root / "questions" / "benchmark"
    question_directory.mkdir(parents=True)
    for index in range(question_count):
        question = _question(index)
        (question_directory / f"{question.id}.md").write_text(
            render_question(question),
            encoding="utf-8",
            newline="\n",
        )
    asset_directory = root / "assets" / "benchmark"
    asset_directory.mkdir(parents=True)
    content = b"qbank benchmark asset\n" * 8
    for index in range(asset_count):
        (asset_directory / f"asset-{index:06d}.bin").write_bytes(content)
    return ProjectContext.from_root(root)


def _seconds(action: Callable[[], Any]) -> float:
    started = time.perf_counter()
    action()
    return time.perf_counter() - started


def _median_seconds(action: Callable[[], Any], repetitions: int) -> float:
    return statistics.median(_seconds(action) for _ in range(repetitions))


def _run_scenario(
    base: Path,
    question_count: int,
    asset_count: int,
    repetitions: int,
) -> dict[str, int | float | str]:
    root = base / f"q{question_count}-a{asset_count}"
    context = _create_fixture(root, question_count, asset_count)
    adapter = QbankMcpAdapter(context)
    rebuild_seconds = _seconds(adapter.services.questions.rebuild_index)
    revision_seconds = _median_seconds(lambda: repository_revision(context), repetitions)
    question_revision_seconds = _median_seconds(
        lambda: question_projection_revision(context),
        repetitions,
    )
    search_seconds = _median_seconds(
        lambda: adapter.question_search(text="benchmark", limit=20),
        repetitions,
    )
    sqlite_summary_seconds = _median_seconds(
        lambda: adapter.services.questions.search_projection("benchmark", limit=20),
        repetitions,
    )
    request = PatchPrepareRequest(
        question_id="BENCH-000000",
        patch=QuestionPatch(set={"title": f"Updated benchmark {question_count}/{asset_count}"}),
    )
    prepared: Any = None

    def prepare() -> None:
        nonlocal prepared
        prepared = adapter.patch_prepare(request)

    prepare_seconds = _seconds(prepare)
    commit_seconds = _seconds(
        lambda: adapter.operation_commit(
            prepared.operation_id,
            prepared.repository_revision,
        )
    )
    return {
        "questions": question_count,
        "assets": asset_count,
        "repository_revision_seconds": round(revision_seconds, 6),
        "question_projection_revision_seconds": round(question_revision_seconds, 6),
        "index_rebuild_seconds": round(rebuild_seconds, 6),
        "search_seconds": round(search_seconds, 6),
        "sqlite_summary_seconds": round(sqlite_summary_seconds, 6),
        "patch_prepare_seconds": round(prepare_seconds, 6),
        "operation_commit_seconds": round(commit_seconds, 6),
        "final_revision": repository_revision(context),
    }


def _parse_scenario(value: str) -> tuple[int, int]:
    try:
        questions_text, assets_text = value.split(":", maxsplit=1)
        questions, assets = int(questions_text), int(assets_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("scenario must use QUESTIONS:ASSETS") from exc
    if questions < 1 or assets < 0:
        raise argparse.ArgumentTypeError("questions must be positive and assets non-negative")
    return questions, assets


def run_benchmarks(
    scenarios: Sequence[tuple[int, int]],
    repetitions: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="qbank-mcp-benchmark-") as temporary:
        base = Path(temporary)
        results = [
            _run_scenario(base, questions, assets, repetitions) for questions, assets in scenarios
        ]
    return {
        "qbank_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repetitions": repetitions,
        "scenarios": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        action="append",
        type=_parse_scenario,
        dest="scenarios",
        help="QUESTIONS:ASSETS; repeat for multiple scenarios",
    )
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.repetitions < 1:
        parser.error("--repetitions must be positive")
    scenarios = arguments.scenarios or [_parse_scenario(item) for item in DEFAULT_SCENARIOS]
    report = run_benchmarks(scenarios, arguments.repetitions)
    rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")


if __name__ == "__main__":
    main()
