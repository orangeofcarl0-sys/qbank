# Expected Codex workflows

## Status prompt

Codex discovers `$qbank`, reads its instructions, runs
`qbank codex check --format json`, then uses `qbank status --format json` or
`qbank doctor --format json`. It does not inspect SQLite directly.

## Source-notes prompt

Codex runs `qbank schema --format json`, reads the source, creates a draft JSONL file
under `build/ai/`, and runs `qbank ingest ... --dry-run --format json`. It does not
formally import because the prompt requests dry-run only.

## Paper prompt

Codex queries reviewed optics summaries, fetches only shortlisted full questions, writes
`papers/generated/<name>.yaml`, validates it, and builds a student Markdown artifact under
`exports/`.

## Quality prompt

Codex queries optics summaries, fetches candidate bodies, reports evidence, and uses only
dry-run structured patches for confirmed changes. It does not directly edit question
Markdown.

## Cross-project prompt

Codex records the explicit qbank root, source path, Workflow A, `dry_run_only`
authorization, and acceptance criteria. It runs qbank commands with the target root as
the working directory, leaves the source project unchanged, and writes any exchange
file under the target bank's `build/ai/`.

## Missing-target prompt

Codex does not select a nearby repository or infer one from prior conversation. It asks
for the target qbank root and, if a mutation is intended, the authorization scope. It
runs no qbank mutation before those are established.

## Handoff prompt

Codex verifies `qbank.yaml`, runs the Codex checks in the recorded target root, and
compares the current `integration_revision` with the handoff. It reports any mismatch
before continuing and preserves the effective authorization boundary.
