# Source analysis and calibration

## Preserve record structure

- Keep a shared stem and dependent subquestions as one composite record.
- Split subquestions only when each is independently understandable and answerable.
- Remove recurring headers, footers, page numbers, and answer-section furniture only
  after verifying the pattern across multiple pages.
- Preserve printed question numbers in provenance, not as the sole qbank ID.

## Handle OCR, formulas, figures, and answers

- Correct only unambiguous OCR errors. Flag uncertain symbols, exponents, subscripts,
  units, option labels, and equation alignment.
- Preserve mathematical meaning over visual whitespace; retain a source image for
  ambiguous formulas when possible.
- Extract a figure only when referenced. Include labels, legend, axes, and nearby
  context required to interpret it.
- Never infer a missing answer or solution. Leave it empty, retain draft status, and
  identify where evidence was expected.
- Link answer-book material only when document identity and numbering are unambiguous.

## Select the sample

Use stratified sampling. Cover every observed archetype:

- plain text and multiple-choice layouts;
- composite questions and page-spanning boundaries;
- formulas, tables, and figures;
- clean text layers and damaged OCR;
- answer-key or solution linkage;
- every materially different classification rule and the unknown path.

Start near 10 questions, then expand until all archetypes and mapping branches are
represented. Sample size is a coverage decision, not a fixed quota.

## Review the calibration

Present for each sample record:

- source page/range and printed number;
- rendered split/merge boundary;
- field policy applications, including constants and ignored values;
- classification rule, conflict, or unknown state;
- OCR/formula/figure evidence and answer provenance;
- qbank dry-run errors and warnings when `$qbank` has been invoked.

Require explicit approval of boundaries, provenance, field semantics,
classification, and special-content handling. A policy change invalidates the
affected portion of the sample and requires recalibration.

## Hand off bounded execution

After approval, recommend small batches and reduce their size when formulas, figures,
or layouts are complex. Generate `questions.jsonl`, existing-Schema Asset packages,
and a `review.md` containing only unresolved items. Preserve the approved sample and
policy in the lightweight working files; do not create a decision-packet service.

Use existing qbank MCP operations for authoritative work. Prepare and validate assets
before dependent questions, inspect every prepared diff, commit only against the
returned repository revision, and validate after commit. `$qbank` owns exact tool
guidance and result reporting.
