# qbank field and classification policy

## Policy modes

Assign every field exactly one primary mode:

- `transcribe`: source-backed content with a preserved location;
- `classify`: value from an approved deterministic mapping;
- `constant`: one user-approved project value, never a per-question guess;
- `generated_label`: retrieval text that is not represented as source wording;
- `system`: mechanically derived version, timestamp, or ID;
- `ignore_as_null` / `ignore_as_empty`: only when the live Schema permits it;
- `review_required`: unresolved, retained as draft, and placed in the review queue.

## Recommended field treatment

| Field | Normal mode | Constraint |
| --- | --- | --- |
| `schema_version` | system | Read the live Schema |
| `id` | system | Freeze a stable pattern before batching |
| `title` | generated label | Keep concise; do not invent a source title |
| `type` | classify | Use `other` when type is intentionally irrelevant |
| `subject` | constant/classify | Use an approved slug |
| `chapter` | classify/null | Null is valid if chapter is irrelevant |
| `topics` | classify | At least one is required; define a fallback |
| `difficulty` | classify/constant | Required 1-5; document non-semantic constants |
| `status` | constant `draft` | OCR/import is not review or verification |
| `language` | constant/detected | Use a stable language tag |
| `source` | transcribe | Include document and page/range |
| `assets` | transcribe/extract | Declare only referenced resources |
| `stem_md` | transcribe | Required and non-empty |
| options | transcribe/empty | Preserve labels and ordering |
| answer/solution | transcribe/empty | Never infer without authority |
| rubric | transcribe/empty | Do not synthesize by default |
| review notes | review evidence | Record OCR, boundary, mapping, and missing evidence |

If the user does not care about a required field, do not pretend the field was
measured. Choose a project constant or fallback, record the decision in the profile,
mark it in review notes when it could be misread, and exclude it from meaningful
downstream filtering.

## Classification-table normalization

Normalize supplied tables to these columns:

| Priority | Source cue | Subject | Chapter | Topics | Type | Confidence rule | Unknown action |
| --- | --- | --- | --- | --- | --- | --- | --- |

Apply the following rules:

- Preserve a supplied classification table as the proposed authority.
- Detect duplicate, overlapping, empty, contradictory, and unreachable rows.
- Prefer stable syllabus/section identifiers over loose keyword guesses.
- Permit multiple topics only when the approved table allows multi-label mapping.
- Route unmatched and conflicting records to review; never invent an ad hoc tag.
- Add proposed canonical tags as pending; do not confuse aliases with canonical slugs.
- Version the normalized mapping and retain the version in the decision packet.

The mapping answers “which approved rule produced this value?” Every calibration
record should expose that rule or state why it is unmatched.
