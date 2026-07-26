---
name: qbank-digitize
description: >
  Turn existing MinerU, OCR, PDF, scan, image, Word, answer-book, or
  classification-table output into reviewable qbank Question JSONL and Asset
  packages. Use when the user needs help deciding question boundaries, relevant
  versus ignored attributes, taxonomy mappings, source fidelity, answer/figure
  handling, or a small calibration sample before existing qbank MCP operations.
  This is a lightweight AI workflow; it does not run OCR or create a job platform.
---

# qbank digitization guide

Turn source extraction into a small, reviewable exchange package. Mirror the user's
language. Use `$qbank` for repository context and deterministic qbank behavior.

## Keep the boundary clear

- Consume existing MinerU or other extraction output. Never install, launch, wrap, or
  upgrade MinerU inside qbank.
- Own source inspection, question boundaries, field semantics, classification,
  formulas, figures, answers, calibration, and the uncertainty review in this Skill.
- Use the target bank's live Question and Asset Schemas. Do not invent a candidate
  Schema or change the qbank Schemas.
- Do not build a Candidate database, durable job service, scheduler, or publishing
  platform.
- Do not redefine qbank commands, MCP tools, repository safety rules, or context
  protocol here.
- MinerU, AI, and source scripts must never edit `questions/`, asset manifests,
  managed assets, history, or SQLite directly.

If the target qbank is unknown, invoke `$qbank` to establish it. Once known, inspect
the existing MinerU output, source evidence, live Schemas, `qbank.yaml`,
`taxonomy.yaml`, representative questions, and any classification table before
asking the user for discoverable facts.

## Use the lightweight phases

- **Discover:** establish source scope, target bank, authority, record boundaries,
  relevant fields, classification authority, and acceptance.
- **Calibrate:** organize a small stratified sample from existing extraction output
  and confirm the source-specific rules.
- **Prepare exchange:** generate only the minimal files below and inspect them.
- **Commit handoff:** use existing qbank MCP prepare/commit operations and validate.
- **Recalibrate:** when the layout or policy changes, repeat only the affected sample
  before continuing.

Do not begin a full-corpus import merely because the extraction is readable.

## Keep one minimal workspace

Use this directory in the source project:

```text
build/digitize/<job-name>/
├─ mineru/
├─ questions.jsonl
├─ assets/
│  └─ packages/
└─ review.md
```

- `mineru/` contains or references existing extraction output.
- `questions.jsonl` contains one object per line that passes the live Question
  Schema.
- `assets/` contains packages accepted by the existing Asset Schema.
- `review.md` contains only genuine uncertainty about question boundaries, formulas,
  figures, answers, or classification. Do not turn it into a full question summary,
  activity log, or duplicate diagnostics report.

Read [references/exchange-workspace.md](references/exchange-workspace.md) before
preparing the exchange. In a Python environment where `qbank` is installed, run
`python .agents/skills/qbank-digitize/scripts/check_exchange.py build/digitize/<job-name>`
and resolve every error before MCP prepare. Inside the qbank implementation
repository, activate `.venv` first or invoke its Python explicitly. The checker is
read-only and prints pure JSON. Cross-project local binaries must be embedded as
Base64 or data URIs; do not pass source-workspace paths to repository-bound MCP
operations.

Read [references/field-policy.md](references/field-policy.md) when fields are
irrelevant or a classification table exists. A small project profile or mapping CSV
may be kept beside the workspace, but it is working guidance rather than a qbank
Schema or database.

## Preserve minimum evidence

For every question preserve:

- source file by stable relative path or content identifier;
- page or page range;
- printed question number when one exists;
- only the review note needed to explain unresolved source, OCR, formula, figure,
  answer, or classification evidence.

Store this through existing `source.reference` and `review_notes_md` fields. Keep
unconfirmed content `draft`. Never invent an answer, condition, classification, or
provenance to make a batch look complete.

## Calibrate and organize

Read [references/intake.md](references/intake.md) for the guided interview and
[references/calibration.md](references/calibration.md) for source handling. Select a
small stratified sample covering materially different layouts, mappings, formulas,
figures, answers, and the unknown path. Ask only 1-3 material judgment questions per
round and never ask the user to restate facts visible in the source or bank.

After sample approval, organize bounded batches into the same three exchange
artifacts. Approval is recorded in the working profile or review record; do not
create a `DigitizationDecisionPacket` or persistent approval service.

## Hand off through existing MCP

Use `$qbank` for exact tool guidance. The authoritative path is:

1. read the live Schemas and current repository revision;
2. prepare Asset packages with `asset_ingest_prepare`;
3. inspect every diff, diagnostic, warning, and revision, then commit approved asset
   operations with `operation_commit`;
4. inspect the committed asset result before preparing dependent questions;
5. prepare `questions.jsonl` with `ingest_prepare`;
6. inspect and commit only while `repository_revision` is unchanged;
7. after both commits, run `question_validate`; this is the existing validation
   boundary for the committed question and its logical assets because there is no
   separate `asset_validate` MCP tool;
8. report committed IDs, warnings, partial success, and remaining `review.md` items.

Question and asset operations are not one cross-operation transaction. Respect
dependency order and report partial success explicitly. On any revision change,
discard the stale operation and prepare again. On validation failure, correct the
exchange files and repeat the workflow; never patch authoritative files directly.

If MCP is unavailable or degraded, pause authoritative agent writes. Use the CLI
compatibility path only when the user explicitly authorizes `$qbank` to do so with
the same dry-run, inspection, and validation boundaries.
