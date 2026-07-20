# qbank examples

## Convert notes into draft questions

Request: “Use `$qbank` to organize `examples/source-notes.md` as drafts. Dry-run only.”

Expected approach:

1. Check the project and read the question schema.
2. Extract only supported source facts.
3. Put uncertain wording in `review_notes_md` and keep status `draft`.
4. Write `build/ai/source-notes.jsonl`.
5. Run ingest with `--dry-run --format json`.
6. Report errors and warnings without formally importing.

## Find incomplete optics questions

Request: “Check optics questions for empty answers or possibly incomplete conditions.”

Expected approach:

1. Query optics summaries with a bounded field list.
2. Fetch full content only for relevant IDs.
3. Report evidence before proposing changes.
4. Use structured patches and dry-run first for confirmed edits.

## Build a reviewed 40-point optics paper

Request: “Select a balanced 40-point paper from reviewed optics questions.”

Expected approach:

1. Query reviewed optics candidates.
2. Inspect shortlisted full questions.
3. Explain selection and score allocation.
4. Write `papers/generated/optics-40.yaml`.
5. Validate the paper.
6. Build `exports/optics-40-student.md` and
   `exports/optics-40-solutions.md`.
