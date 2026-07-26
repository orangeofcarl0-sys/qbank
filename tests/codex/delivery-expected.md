# Expected qbank-deliver behavior

The Skill establishes one explicit qbank root and repository revision, searches
before fetching full questions, and saves ordered Question JSONL and complete
`asset_get` snapshots. It writes a transparent `selection.yaml` and controlled
`content.tex`, then calls only the bundled builder.

The builder refuses revision drift, missing or reordered IDs, undeclared assets,
remote representations, path escapes, symlinks, changed hashes, arbitrary TeX file
commands, and absolute paths. It reads the bank without mutation, stages output
outside the bank, and replaces the output directory only after success.

Draft or incomplete content warns and continues. The fixed template marks draft
questions and renders missing answer or solution content as `未提供`; the Skill never
invents content.
