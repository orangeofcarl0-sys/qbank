# qbank examples

## Import from another project with explicit context

Request: "Use `$qbank` to organize `<source-project>/notes.md` into the question bank
at `<qbank-root>`. Dry-run only; do not modify the source project."

Expected approach:

1. Record `<qbank-root>` as the target, the notes path as the source, Workflow A, and
   `dry_run_only` authorization.
2. Verify `qbank.yaml` and run the Codex checks with `<qbank-root>` as working directory.
3. Read the source without writing beside it.
4. Put exchange data under `<qbank-root>/build/ai/` and run ingest dry-run only.
5. Report a completion handoff with the target, source, commands, diagnostics, and next step.

If `<qbank-root>` is missing or ambiguous, ask for it before running qbank. Do not choose
a nearby repository by name.

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

## Revise a logical asset

Request: “Update figure-1 for OPT-INT-0001 from this confirmed source package.”

Expected approach:

1. Read the asset-package Schema and inspect the current manifest.
2. Put the proposed package under `build/ai/`.
3. Dry-run asset ingest and report every representation change.
4. Commit only after the proposed diff is accepted.
5. Run asset validation.

## Normalize a project tag

Request: “Rename the confirmed legacy tag `wave_optics` to `wave-optics`.”

Expected approach:

1. Inspect tag usage and affected questions.
2. Dry-run the rename and report the full question diff.
3. Commit the same operation only after confirmation.
4. Validate the repository.
