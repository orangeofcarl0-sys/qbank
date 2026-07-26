#!/usr/bin/env python3
"""Run the public synthetic digitize-to-delivery workflow in a new local directory."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from qbank.context import ProjectContext
from qbank.mcp.adapter import QbankMcpAdapter
from qbank.models import (
    AssetIngestPrepareRequest,
    AssetPackage,
    IngestPrepareRequest,
    QueryFilters,
    Question,
)
from qbank.project import initialize_project
from qbank.yaml_io import dump_yaml

EXAMPLE = Path(__file__).resolve().parent
QUESTION_IDS = ("DEMO-MATH-0001", "DEMO-FIG-0001")


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _questions() -> list[Question]:
    path = EXAMPLE / "digitize" / "questions.jsonl"
    return [
        Question.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _commit(adapter: QbankMcpAdapter, prepared: Any) -> None:
    if not prepared.committable:
        raise RuntimeError(f"MCP prepare was not committable: {prepared.model_dump_json()}")
    adapter.operation_commit(prepared.operation_id, prepared.repository_revision)


def _import_exchange(adapter: QbankMcpAdapter) -> list[Question]:
    adapter.schema_get("question")
    package_path = next((EXAMPLE / "digitize" / "assets" / "packages").glob("*.json"))
    package = AssetPackage.model_validate_json(package_path.read_text(encoding="utf-8"))
    _commit(
        adapter,
        adapter.asset_ingest_prepare(AssetIngestPrepareRequest(package=package)),
    )
    questions = _questions()
    _commit(
        adapter,
        adapter.ingest_prepare(IngestPrepareRequest(questions=questions)),
    )
    validation = adapter.question_validate()
    if not validation.ok:
        raise RuntimeError(f"qbank validation failed: {validation.model_dump_json()}")
    return questions


def _freeze_snapshot(
    adapter: QbankMcpAdapter,
    questions: list[Question],
    workspace: Path,
) -> None:
    (workspace / "snapshot" / "assets" / "DEMO-FIG-0001").mkdir(parents=True)
    found = adapter.question_search(filters=QueryFilters(subject="synthetic"), limit=20)
    if {item.id for item in found.items} != set(QUESTION_IDS):
        raise RuntimeError("MCP search did not return the expected synthetic questions")
    selected = [adapter.question_get(question.id) for question in questions]
    (workspace / "snapshot" / "questions.jsonl").write_text(
        "".join(question.model_dump_json() + "\n" for question in selected),
        encoding="utf-8",
        newline="\n",
    )
    asset = adapter.asset_get("DEMO-FIG-0001", "figure-1")
    (workspace / "snapshot" / "assets" / "DEMO-FIG-0001" / "figure-1.json").write_text(
        asset.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_delivery_contract(adapter: QbankMcpAdapter, workspace: Path) -> None:
    shutil.copy2(EXAMPLE / "deliver" / "content.tex", workspace / "content.tex")
    selection = {
        "version": "1",
        "repository_revision": adapter.revision(),
        "template": "qbank-zh-exam-v1",
        "variant": "solution",
        "document": {
            "title": "qbank 合成示例试卷",
            "subject": "示例学科",
            "date": "2026-07-26",
            "duration_minutes": 30,
        },
        "questions": [
            {"id": "DEMO-MATH-0001", "score": 10, "assets": {}},
            {
                "id": "DEMO-FIG-0001",
                "score": 10,
                "assets": {"figure-1": "render-png"},
            },
        ],
    }
    (workspace / "selection.yaml").write_text(
        dump_yaml(selection) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run(destination: Path, *, compile_pdf: bool = True) -> dict[str, Any]:
    """Create a fresh qbank and run the synthetic exchange through the real adapter."""
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError(f"destination must be absent or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    bank = initialize_project(destination / "bank")
    adapter = QbankMcpAdapter(ProjectContext.from_root(bank))
    questions = _import_exchange(adapter)
    workspace = destination / "delivery"
    _freeze_snapshot(adapter, questions, workspace)
    _write_delivery_contract(adapter, workspace)
    helper = _load_module(
        "qbank_public_delivery_demo",
        bank / ".agents" / "skills" / "qbank-deliver" / "scripts" / "build_delivery.py",
    )
    summary = helper.build(workspace, bank, compile_pdf=compile_pdf)
    return {
        "ok": True,
        "qbank_root": str(bank),
        "delivery_workspace": str(workspace),
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--skip-tex",
        action="store_true",
        help="Create and validate the delivery snapshot without compiling a PDF.",
    )
    args = parser.parse_args()
    try:
        result = run(args.destination, compile_pdf=not args.skip_tex)
    except (OSError, RuntimeError, ValueError) as exc:
        result = {"ok": False, "error": str(exc)}
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 3
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
