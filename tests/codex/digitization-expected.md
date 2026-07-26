# Expected qbank-digitize behavior

## Classification-table project

The Skill inspects the source structure, live qbank Schema, taxonomy, and supplied
classification table before asking. It recommends `calibrated_batch` and asks at most
three high-impact judgment questions per round. It distinguishes allowed empty fields
from required fields, requests an explicit non-semantic policy for difficulty, checks
the classification table for conflicts and unknowns, and stops before full import.

## Changed source archetype

The Skill compares the approved profile with the new page-spanning composite and answer
linkage behavior. It selects `recalibrate`, invalidates only affected sample coverage,
and does not hand execution to `$qbank` until the revised sample is approved.

## Small scan

The Skill may recommend `quick_capture` after confirming the record unit and source
reference policy. It keeps every record draft, leaves answers empty, flags ambiguous
OCR, and hands only a dry-run scope to `$qbank`.

## Separation invariant

`$qbank-digitize` produces only `questions.jsonl`, existing-Schema Asset packages, a
fixed-table `review.md`, and a read-only JSON validation report. `$qbank` remains
responsible for target discovery, authorization, mutations, validation, and handoff.
Cross-project local binaries are embedded in packages and never represented by source
workspace paths.
