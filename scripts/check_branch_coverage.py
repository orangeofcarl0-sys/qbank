"""Enforce statement and branch coverage thresholds from Coverage.py JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

STATEMENT_MINIMUM = 90.0
OVERALL_BRANCH_MINIMUM = 85.0
LAYER_BRANCH_MINIMUM = 90.0
LAYER_PREFIXES = {
    "application": "src/qbank/application/",
    "domain": "src/qbank/domain/",
}


def _percentage(covered: int, total: int) -> float:
    return 100.0 if total == 0 else covered * 100.0 / total


def _branch_totals(
    files: dict[str, dict[str, Any]],
    prefix: str,
) -> tuple[int, int, int]:
    covered = 0
    total = 0
    matched = 0
    for name, details in files.items():
        normalized = name.replace("\\", "/")
        if not normalized.startswith(prefix):
            continue
        matched += 1
        summary = cast(dict[str, int], details["summary"])
        covered += summary["covered_branches"]
        total += summary["num_branches"]
    return covered, total, matched


def check(path: Path) -> list[str]:
    """Return human-readable threshold failures for one coverage report."""
    report = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    metadata = cast(dict[str, Any], report.get("meta", {}))
    totals = cast(dict[str, int | float], report["totals"])
    failures: list[str] = []
    if metadata.get("branch_coverage") is not True:
        failures.append("coverage report was not generated with branch measurement enabled")
    statements = float(totals["percent_statements_covered"])
    if statements < STATEMENT_MINIMUM:
        failures.append(f"statement coverage {statements:.2f}% is below {STATEMENT_MINIMUM:.2f}%")
    total_branches = int(totals["num_branches"])
    overall_branches = _percentage(int(totals["covered_branches"]), total_branches)
    if total_branches == 0:
        failures.append("coverage report contains no measured branches")
    elif overall_branches < OVERALL_BRANCH_MINIMUM:
        failures.append(
            f"overall branch coverage {overall_branches:.2f}% "
            f"is below {OVERALL_BRANCH_MINIMUM:.2f}%"
        )
    files = cast(dict[str, dict[str, Any]], report["files"])
    for layer, prefix in LAYER_PREFIXES.items():
        covered, total, matched = _branch_totals(files, prefix)
        percentage = _percentage(covered, total)
        if matched == 0:
            failures.append(f"coverage report contains no files for the {layer} layer")
        elif total == 0:
            failures.append(f"coverage report contains no measured branches for the {layer} layer")
        elif percentage < LAYER_BRANCH_MINIMUM:
            failures.append(
                f"{layer} branch coverage {percentage:.2f}% is below {LAYER_BRANCH_MINIMUM:.2f}%"
            )
    return failures


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build/audit/coverage.json")
    failures = check(path)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("Coverage thresholds satisfied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
