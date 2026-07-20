# Code review guide

## Review order

1. Confirm data ownership: Markdown remains authoritative and derived state is
   not treated as source data.
2. Confirm dependency direction with `lint-imports` and the import-cycle test.
3. Trace public JSON, CLI, schema, Markdown, and exit-code compatibility.
4. Review failure paths before happy paths: partial commits, rollback failure,
   missing/corrupt index, malformed source, and external tool failure.
5. Check that new behavior is expressed through typed models and existing
   field/section descriptors instead of duplicate strings or dictionaries.
6. Require deterministic ordering and a focused regression test.

## Severity

- **P0**: data loss, silent corruption, arbitrary code execution, or a release
  blocker affecting all users.
- **P1**: incorrect public behavior, broken atomicity, security boundary
  failure, or an architectural dependency that makes a supported extension
  unsafe.
- **P2**: maintainability or correctness risk with a practical failure mode,
  including contract drift, ambiguous ownership, or weak failure coverage.
- **P3**: localized readability, naming, documentation, or low-risk cleanup.

Every finding must include file/line evidence, impact, a minimal fix, and a
verification step. Avoid speculative redesign without a demonstrated boundary
or failure.

## Required checks

```text
ruff format --check .
ruff check .
pyright
lint-imports
deptry .
pytest
pytest --cov=qbank --cov-branch --cov-fail-under=0 --cov-report=json:build/audit/coverage.json
python scripts/check_branch_coverage.py build/audit/coverage.json
pip check
pip-audit
python -m pip wheel . --no-deps --no-build-isolation
python -m qbank --help
```

Overall branch coverage must be at least 85%. Domain and application branch
coverage must each be at least 90%.

## Readability checklist

- One name for each concept; no parallel “record/item/document” meanings.
- Functions describe one policy or one orchestration step.
- No broad exception handling inside domain/application logic.
- Comments explain constraints and tradeoffs, not the syntax below them.
- Public adapters preserve type and error semantics.
- New compatibility exceptions have an owner and removal condition.
