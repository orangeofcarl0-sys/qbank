# qbank workflows

## A. Organize and import questions

1. Run `qbank doctor --format json`.
2. Run `qbank schema --format json`.
3. Read the input PDF, image, Word, Markdown, or text source.
4. Generate `build/ai/<job-name>.jsonl`.
5. Run `qbank ingest <file> --dry-run --format json`.
6. Fix every error without inventing missing information.
7. Run `qbank ingest <file> --format json`.
8. Run `qbank validate --format json`.
9. Run `qbank preview`.
10. Report added IDs, warnings, and questions needing review.

Keep an incomplete or uncertain question in `draft`. Preserve source location. Keep
AI inference distinguishable from source text. Put OCR or parsing uncertainty in
`review_notes_md`.

## B. Inspect and revise the bank

1. Use `qbank query` to retrieve summaries within a defined scope.
2. Use `qbank get` only for candidate IDs that need full inspection.
3. Produce a diagnostic report before changing data.
4. Create a structured JSON patch only for confirmed revisions.
5. Run `qbank patch ID --file PATCH --dry-run --format json`.
6. Inspect every field-level difference.
7. Apply the same patch without `--dry-run`.
8. Run `qbank validate --format json`.

Never perform an unscoped bulk overwrite. Do not replace malformed Markdown; report it
for manual repair or explicit deletion.

## C. Search and select questions

1. Start with `qbank query` and short fields.
2. Use `qbank search` only when metadata filtering is insufficient.
3. Use `qbank get` only for candidate IDs.
4. Avoid loading the entire bank into context.
5. Return selected IDs and a reason for each choice.

Request these fields first:

```text
id,title,subject,chapter,topics,type,difficulty,status
```

## D. Assemble a paper

1. Translate the request into explicit subject, chapter, topic, type, difficulty,
   status, score, and count constraints.
2. Query candidate summaries.
3. Fetch full bodies only for shortlisted IDs.
4. Check scope, difficulty, type balance, repeated knowledge points, status, and score.
5. Generate `papers/generated/<paper-name>.yaml`.
6. Run `qbank paper validate <paper> --format json`.
7. Fix every validation error.
8. Build the student version.
9. Build the answer or solution version.
10. Report composition, selected IDs, warnings, and output paths.

Codex selects and orders questions. qbank performs deterministic validation and rendering;
do not implement or assume an automatic selection algorithm.
