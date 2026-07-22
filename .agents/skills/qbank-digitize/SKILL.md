---
name: qbank-digitize
description: >
  Guide real-world PDF, scan, image, Word, OCR, answer-book, or classification-table
  projects into an approved qbank digitization profile and representative calibration
  sample. Use when the user needs help deciding question boundaries, relevant versus
  ignored attributes, taxonomy mappings, source fidelity, answer/figure handling,
  review gates, or batch strategy before importing. This is a domain-planning and
  calibration tool; hand deterministic qbank operations to $qbank.
---

# qbank digitization guide

Turn an underspecified source-digitization request into a source-grounded,
decision-complete profile and approved calibration sample. Mirror the user's language.

## Keep the boundary clear

- Own discovery, expert questioning, field semantics, classification policy,
  sampling, and acceptance criteria in this Skill.
- Use `$qbank` to locate the target bank, read its live Schema, execute dry-runs,
  commit records, validate, and produce a cross-task handoff.
- Do not redefine qbank commands, repository safety rules, or context protocol here.
- Do not begin a full-corpus import merely because the source is readable.

If the target qbank is unknown, invoke `$qbank` to establish it. Once known, inspect
the source, live question Schema, `qbank.yaml`, `taxonomy.yaml`, representative
questions, and any classification table before asking the user for discoverable facts.

## Select the current phase

- **Discover:** no approved digitization profile exists. Run the guided interview.
- **Calibrate:** a profile exists but source archetypes or mappings are unverified.
- **Execute handoff:** the user approved the profile and sample. Pass bounded work to
  `$qbank`; do not duplicate its mutation workflow.
- **Recalibrate:** source layout, classification rules, or field meaning changed.
  Version the profile and repeat only the affected sample.

## Run the guided interview

Read [references/intake.md](references/intake.md). Ask only 1-3 material judgment
questions per round. Before each round, briefly state:

- the current understanding;
- evidence already observed;
- why these questions matter now;
- what downstream decision they control.

Prefer 2-3 bounded choices. Put the recommended choice first and explain each
choice's consequence. Never ask the user to restate facts visible in the source or
repository. Do not dump a long generic questionnaire.

Close discovery only when these areas are decided, evidenced, explicitly defaulted,
or deferred with a consequence:

1. intended use and non-goals;
2. question record unit and composite/subquestion policy;
3. relevant, ignored, constant, generated, and review-required fields;
4. classification authority, mapping rules, conflicts, and unknown handling;
5. page, numbering, OCR, formula, figure, answer, and solution evidence;
6. calibration coverage, approval owner, batch size, and partial-failure policy.

## Produce working artifacts

Read [references/field-policy.md](references/field-policy.md) when the user has a
classification table or does not care about some qbank attributes. Copy:

- `assets/digitization-profile.yaml` to `build/ai/<job>/profile.yaml`;
- `assets/classification-map.csv` to `build/ai/<job>/classification-map.csv` when
  normalization is needed.

The profile records decisions for Codex; it never replaces the live qbank Schema.
Do not silently infer a Schema-required field that the user considers irrelevant.
Choose an explicit project constant, safe fallback, or review rule and document its
meaning.

## Calibrate before execution

Read [references/calibration.md](references/calibration.md). Select a stratified
sample that covers all observed source archetypes, not just the first pages. Build
only a calibration proposal until the user accepts:

- question split/merge boundaries;
- source references and printed numbering;
- field constants, ignored values, and generated labels;
- classification matches, conflicts, and unknowns;
- OCR, formulas, figures, answers, and missing evidence.

After approval, emit a compact `digitization_decision_packet` containing the profile
path, source scope, approved sample, mapping version, unresolved review queue, batch
limits, acceptance criteria, and effective authorization. Then invoke `$qbank` for
the actual dry-run-first import. If approval is absent, stop at the calibration report.
