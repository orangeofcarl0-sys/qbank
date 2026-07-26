#!/usr/bin/env python3
"""Validate one lightweight qbank digitization exchange workspace."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import unquote_to_bytes

from pydantic import ValidationError

from qbank.asset_references import AssetKind, classify_resource_uri, extract_image_resources
from qbank.models import AssetPackage, Question

REVIEW_HEADER = (
    "| Question ID | Source | Page | Issue | Required decision |",
    "| --- | --- | --- | --- | --- |",
)
DATA_URI = re.compile(r"^data:([^;,]*)(;base64)?,(.*)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    level: str
    code: str
    message: str
    file: str
    line: int | None = None


def _diagnostic(
    diagnostics: list[Diagnostic],
    code: str,
    message: str,
    path: Path,
    *,
    line: int | None = None,
    level: str = "error",
) -> None:
    diagnostics.append(Diagnostic(level, code, message, path.as_posix(), line))


def _questions(path: Path, diagnostics: list[Diagnostic]) -> list[Question]:
    questions: list[Question] = []
    seen: set[str] = set()
    if not path.is_file():
        _diagnostic(diagnostics, "missing_questions", "questions.jsonl is missing", path)
        return questions
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            question = Question.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            _diagnostic(diagnostics, "invalid_question", str(exc), path, line=number)
            continue
        if question.id in seen:
            _diagnostic(
                diagnostics,
                "duplicate_question_id",
                f"duplicate question ID: {question.id}",
                path,
                line=number,
            )
            continue
        seen.add(question.id)
        _check_source(question, path, number, diagnostics)
        questions.append(question)
    return questions


def _check_source(
    question: Question,
    path: Path,
    line: int,
    diagnostics: list[Diagnostic],
) -> None:
    reference = question.source.reference or ""
    windows = PureWindowsPath(reference)
    posix = PurePosixPath(reference.replace("\\", "/"))
    if not reference:
        _diagnostic(
            diagnostics,
            "missing_source_reference",
            f"{question.id} has no source.reference",
            path,
            line=line,
        )
        return
    if windows.is_absolute() or posix.is_absolute() or (windows.drive and windows.root):
        _diagnostic(
            diagnostics,
            "absolute_source_reference",
            f"{question.id} contains a machine-specific source path",
            path,
            line=line,
        )
    if re.search(r"(?:page|pages|页)\s*(?:=|:)?\s*\d+", reference, re.IGNORECASE) is None:
        _diagnostic(
            diagnostics,
            "missing_source_page",
            f"{question.id} source.reference does not identify a page",
            path,
            line=line,
        )


def _decode_representation(representation: Any) -> bytes | None:
    if representation.base64 is not None:
        return base64.b64decode(representation.base64, validate=True)
    if representation.data_uri is not None:
        match = DATA_URI.fullmatch(representation.data_uri)
        if match is None:
            raise ValueError("malformed data URI")
        _, encoded, payload = match.groups()
        return base64.b64decode(payload, validate=True) if encoded else unquote_to_bytes(payload)
    return None


def _check_package_representation(
    representation: Any,
    path: Path,
    diagnostics: list[Diagnostic],
) -> None:
    if representation.path is not None:
        _diagnostic(
            diagnostics,
            "path_backed_asset",
            "cross-project packages must embed local content instead of using path",
            path,
        )
        return
    if representation.url is not None:
        _diagnostic(
            diagnostics,
            "external_asset",
            f"external representation retained without download: {representation.url}",
            path,
            level="warning",
        )
        return
    try:
        content = _decode_representation(representation)
        if (
            content is not None
            and representation.content_hash is not None
            and hashlib.sha256(content).hexdigest() != representation.content_hash
        ):
            raise ValueError("embedded content does not match content_hash")
    except (ValueError, binascii.Error) as exc:
        _diagnostic(
            diagnostics,
            "invalid_embedded_asset",
            f"{representation.representation_id}: {exc}",
            path,
        )


def _packages(
    root: Path,
    questions: dict[str, Question],
    diagnostics: list[Diagnostic],
) -> dict[tuple[str, str], AssetPackage]:
    packages: dict[tuple[str, str], AssetPackage] = {}
    if not root.is_dir():
        return packages
    for path in sorted(root.glob("*.json")):
        try:
            package = AssetPackage.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            _diagnostic(diagnostics, "invalid_asset_package", str(exc), path)
            continue
        key = (package.question_id, package.asset_id)
        if key in packages:
            _diagnostic(
                diagnostics,
                "duplicate_asset_package",
                f"duplicate package: {package.question_id}/{package.asset_id}",
                path,
            )
            continue
        if package.question_id not in questions:
            _diagnostic(
                diagnostics,
                "unknown_asset_question",
                f"package targets a question outside questions.jsonl: {package.question_id}",
                path,
            )
        for representation in package.representations:
            _check_package_representation(representation, path, diagnostics)
        if not package.provenance.get("source") or not package.provenance.get("page"):
            _diagnostic(
                diagnostics,
                "missing_asset_provenance",
                "asset package provenance must identify source and page",
                path,
            )
        packages[key] = package
    return packages


def _logical_ids(question: Question) -> tuple[set[str], set[str]]:
    declared = {
        reference.asset_id
        for raw in question.assets
        if (reference := classify_resource_uri(raw)).kind == AssetKind.LOGICAL
        and reference.asset_id
    }
    referenced = {
        reference.asset_id
        for raw in extract_image_resources(question)
        if (reference := classify_resource_uri(raw)).kind == AssetKind.LOGICAL
        and reference.asset_id
    }
    return declared, referenced


def _asset_links(
    questions: dict[str, Question],
    packages: dict[tuple[str, str], AssetPackage],
    path: Path,
    diagnostics: list[Diagnostic],
) -> None:
    declared_keys: set[tuple[str, str]] = set()
    for question in questions.values():
        declared, referenced = _logical_ids(question)
        if len(declared) != len(question.assets):
            _diagnostic(
                diagnostics,
                "nonlogical_asset_declaration",
                f"{question.id} contains a non-logical asset declaration",
                path,
            )
        for asset_id in sorted(declared - referenced):
            _diagnostic(
                diagnostics,
                "unused_asset",
                f"{question.id} declares but does not reference {asset_id}",
                path,
                level="warning",
            )
        for asset_id in sorted(referenced - declared):
            _diagnostic(
                diagnostics,
                "undeclared_asset_reference",
                f"{question.id} references but does not declare {asset_id}",
                path,
            )
        for asset_id in sorted(declared):
            key = (question.id, asset_id)
            declared_keys.add(key)
            if key not in packages:
                _diagnostic(
                    diagnostics,
                    "missing_asset_package",
                    f"missing package for {question.id}/{asset_id}",
                    path,
                )
    for question_id, asset_id in sorted(set(packages) - declared_keys):
        _diagnostic(
            diagnostics,
            "orphan_asset_package",
            f"package is not declared by its question: {question_id}/{asset_id}",
            path,
        )


def _review(
    path: Path,
    questions: dict[str, Question],
    diagnostics: list[Diagnostic],
) -> int:
    if not path.is_file():
        _diagnostic(diagnostics, "missing_review", "review.md is missing", path)
        return 0
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if tuple(lines[:2]) != REVIEW_HEADER:
        _diagnostic(
            diagnostics, "invalid_review_header", "review.md has the wrong table header", path
        )
        return 0
    count = 0
    for number, line in enumerate(lines[2:], start=3):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 5 or any(not cell for cell in cells):
            _diagnostic(
                diagnostics,
                "invalid_review_row",
                "review row must contain five non-empty cells",
                path,
                line=number,
            )
            continue
        question = questions.get(cells[0])
        if question is None:
            _diagnostic(
                diagnostics,
                "unknown_review_question",
                f"review row targets unknown question: {cells[0]}",
                path,
                line=number,
            )
        elif question.status.value != "draft":
            _diagnostic(
                diagnostics,
                "review_question_not_draft",
                f"review row targets non-draft question: {cells[0]}",
                path,
                line=number,
            )
        count += 1
    return count


def check(workspace: Path) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    question_list = _questions(workspace / "questions.jsonl", diagnostics)
    questions = {question.id: question for question in question_list}
    packages = _packages(workspace / "assets" / "packages", questions, diagnostics)
    _asset_links(questions, packages, workspace / "questions.jsonl", diagnostics)
    review_items = _review(workspace / "review.md", questions, diagnostics)
    return {
        "ok": not any(item.level == "error" for item in diagnostics),
        "workspace": str(workspace.resolve()),
        "questions": len(questions),
        "asset_packages": len(packages),
        "review_items": review_items,
        "diagnostics": [asdict(item) for item in diagnostics],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    result = check(args.workspace)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
