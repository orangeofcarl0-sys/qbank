"""Question exchange JSON parsing at the application boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from pydantic import ValidationError

from qbank.errors import DataValidationError
from qbank.models import Diagnostic, DiagnosticCode, Question


@dataclass(frozen=True)
class JsonLineRecord:
    """One independently parsed JSONL input record."""

    line: int
    question: Question | None
    errors: list[Diagnostic]


def load_json_records(text: str, *, jsonl: bool) -> list[Question]:
    """Validate JSON or JSONL text into complete questions."""
    try:
        if jsonl:
            parsed_lines = parse_json_lines(text)
            invalid = [record for record in parsed_lines if record.errors]
            if invalid:
                messages = [f"line {record.line}: {record.errors[0].message}" for record in invalid]
                raise DataValidationError("\n".join(messages))
            return [record.question for record in parsed_lines if record.question is not None]
        parsed: object = json.loads(text)
        records = cast(list[object], parsed) if isinstance(parsed, list) else [parsed]
        return [Question.model_validate(item) for item in records]
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise DataValidationError(str(exc)) from exc


def parse_json_lines(text: str) -> list[JsonLineRecord]:
    """Parse JSONL independently while retaining physical line numbers."""
    records: list[JsonLineRecord] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        records.append(_parse_json_line(line, line_number))
    return records


def _parse_json_line(line: str, line_number: int) -> JsonLineRecord:
    try:
        raw = json.loads(line)
    except (json.JSONDecodeError, TypeError) as exc:
        return JsonLineRecord(
            line=line_number,
            question=None,
            errors=[Diagnostic(code=DiagnosticCode.INVALID_JSON, message=str(exc))],
        )
    try:
        question = Question.model_validate(raw)
    except ValidationError as exc:
        errors = [
            Diagnostic(
                code=DiagnosticCode.MODEL_VALIDATION,
                field=".".join(str(part) for part in error["loc"]),
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        return JsonLineRecord(line=line_number, question=None, errors=errors)
    return JsonLineRecord(line=line_number, question=question, errors=[])
