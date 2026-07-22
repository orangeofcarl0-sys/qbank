# Guided digitization intake

## Research sweep

Inspect the available artifacts before asking questions:

- source count, page count, text layer, scan quality, columns, recurring furniture,
  numbering, question boundaries, answer sections, formulas, tables, and figures;
- the live qbank question Schema, defaults, taxonomy, saved views, and representative
  records;
- supplied classification sheets, syllabus codes, chapter indices, answer keys,
  naming conventions, and prior digitization samples.

Classify each relevant item as observed, safely inferred, unverified, unavailable,
or requiring user judgment. Ask only about the final category or unavailable facts
that materially affect the outcome.

## Operating modes

| Mode | Recommend when | Consequence |
| --- | --- | --- |
| `calibrated_batch` | Normal multi-question project | Profile, stratified sample, approval, bounded batches |
| `quick_capture` | Small uniform source with low reuse | Minimal interview; all records remain draft |
| `source_faithful` | Archival or high-stakes edition | Preserve wording/evidence; classify conservatively |

Default to `calibrated_batch` for a real PDF corpus.

## Decision lanes

Probe the highest-leverage unresolved lane first:

1. **Outcome:** searchable archive, practice bank, paper assembly, or faithful edition.
2. **Record unit:** whole numbered question, independent subquestion, or composite.
3. **Field meaning:** source fact, classification, constant, generated label, ignored,
   or human review.
4. **Classification authority:** supplied table, existing taxonomy, approved new
   mapping, or model proposal requiring approval.
5. **Evidence:** document/page identity, printed number, OCR uncertainty, formulas,
   figures, answer and solution provenance.
6. **Acceptance:** sample coverage, approver, allowed warning rate, batch size,
   partial imports, and completion proof.

## Question format

Use a compact context followed by at most three atomic questions. For each bounded
question, put the recommended option first and state the downstream effect.

Example:

> Difficulty is required by qbank but is not used by this project. Choose: (1)
> project constant 3 with explicit non-semantic annotation (recommended), (2) human
> review for every question, or (3) Codex estimate marked as inferred. This determines
> whether difficulty can be trusted for filtering and how much review is required.

Do not ask all lanes at once. After each answer, update the working profile and pull
only on newly material branches.

## Closure

Discovery is complete only when every material lane is observed, answered, assumed
with consequence, or explicitly deferred. Summarize the decisions in the profile;
do not rely on conversational memory as the project record.
