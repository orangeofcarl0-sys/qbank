---
name: qbank
description: >
  Manage, inspect, import, revise, search, select, and export questions from
  a qbank repository, including when the source material or active task is in
  another project. Use when organizing questions from PDF, images, Word,
  Markdown, or text; importing batches; auditing or revising question quality;
  finding duplicates, missing conditions, or incomplete answers; searching and
  selecting questions; assembling paper.yaml; or exporting student, answer,
  solution, or question-list artifacts. Do not use for ordinary knowledge
  questions, unrelated writing, online exam management, automatic grading, or
  learning-progress tracking.
---

# qbank

Operate the local question bank through `qbank`. Treat Markdown as authoritative,
JSON/JSONL as exchange data, and SQLite as a disposable projection.

## Start safely

1. Establish the target qbank root, source locations, objective, workflow,
   authorization, acceptance criteria, and unresolved questions.
2. Run qbank commands with the target qbank root as the working directory.
3. Treat any other source project as read-only unless the user explicitly
   authorizes writes there.
4. Run `qbank codex check --format json`.
5. Before creating exchange data, run `qbank schema --format json`.
6. Prefer JSON output for inspection and automation.
7. Never edit `questions/**/*.md` or `.qbank/index.sqlite` directly by default.
8. Dry-run every write, inspect errors and warnings, then execute it.
9. After a write, run `qbank validate --format json`.
10. Run destructive operations only after an explicit user request.
11. Do not start blocking interactive commands in unattended work.

If `qbank codex integration-status --format json` reports a registered MCP server,
prefer its typed tools for bounded automation. Search before fetching full questions.
All MCP mutations require `*_prepare`, inspection of the field diff and diagnostics,
then `operation_commit` with the returned `repository_revision`. If that revision has
changed, discard the operation and prepare again. The CLI workflow remains the fallback
when MCP is absent or degraded.

Read [references/context-handoff.md](references/context-handoff.md) before acting
from another project, resuming handed-off work, or proceeding with incomplete
conversation context. Do not guess the target repository or write authorization.

## Route the request

- To define or recalibrate a PDF-to-qbank project, use `$qbank-digitize` first;
  resume this Skill only after it returns an approved decision packet.
- To organize source documents or batch-import questions, follow Workflow A.
- To audit or revise existing questions, follow Workflow B.
- To search and select candidates, follow Workflow C.
- To assemble and export a paper, follow Workflow D.
- To create or revise logical assets, follow Workflow E.
- To manage tags or saved views, follow Workflow F.
- To rebuild projections, delete data, or launch an interactive UI, follow Workflow G.

Read [references/workflows.md](references/workflows.md) before performing the
selected workflow. Read [references/command-reference.md](references/command-reference.md)
when choosing flags or output formats. Read [references/examples.md](references/examples.md)
for concrete request-to-command patterns.

## Preserve evidence

- Put temporary AI exchange files in `build/ai/`.
- Put generated paper definitions in `papers/generated/`.
- Put final exports in `exports/`.
- Preserve source references and source locations.
- Record OCR ambiguity or parsing uncertainty in `review_notes_md`.
- Keep AI inference distinguishable from source content.
- Keep unconfirmed questions in `draft`; never invent answers or provenance.
- Report created or selected IDs, warnings, review needs, and output paths.

## Control context size

Query short fields first. Fetch full question bodies only for candidate IDs. Do not
load the entire repository into the model context when a filtered query is sufficient.
