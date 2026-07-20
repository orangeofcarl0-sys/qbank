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
