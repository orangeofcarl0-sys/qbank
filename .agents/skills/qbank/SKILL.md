---
name: qbank
description: >
  Manage, inspect, import, revise, search, select, and export questions from
  the local qbank repository. Use when organizing questions from PDF, images,
  Word, Markdown, or text; importing batches; auditing or revising question
  quality; finding duplicates, missing conditions, or incomplete answers;
  searching and selecting questions; assembling paper.yaml; or exporting
  student, answer, solution, or question-list artifacts. Do not use for
  ordinary knowledge questions, unrelated writing, online exam management,
  automatic grading, or learning-progress tracking.
---

# qbank

Operate the local question bank through `qbank`. Treat Markdown as authoritative,
JSON/JSONL as exchange data, and SQLite as a disposable projection.

## Start safely

1. Work from the qbank project root or a descendant.
2. Run `qbank codex check --format json`.
3. Before creating exchange data, run `qbank schema --format json`.
4. Prefer JSON output for inspection and automation.
5. Never edit `questions/**/*.md` or `.qbank/index.sqlite` directly by default.
6. Dry-run every write, inspect errors and warnings, then execute it.
7. After a write, run `qbank validate --format json`.

## Route the request

- To organize source documents or batch-import questions, follow Workflow A.
- To audit or revise existing questions, follow Workflow B.
- To search and select candidates, follow Workflow C.
- To assemble and export a paper, follow Workflow D.

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
