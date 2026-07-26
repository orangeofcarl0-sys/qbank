---
name: qbank-deliver
description: >
  Build a reproducible Chinese exam PDF from selected qbank questions without
  modifying the bank. Use when an agent must search and freeze questions through
  qbank MCP, select logical-asset representations, generate controlled TeX, or
  produce student, answer, and solution editions with a fixed XeLaTeX template.
---

# qbank deliver

Create a formal document from an explicit, read-only qbank snapshot. Use `$qbank`
to establish the target repository and MCP context. Never modify the bank from this
Skill.

## Follow the bounded workflow

1. Read `repository_status` and retain its `repository_revision`.
2. Use `question_search` for discovery and `question_get` only for selected IDs.
3. Save the selected Question objects, in order, as
   `build/deliver/<job>/snapshot/questions.jsonl`.
4. Call `asset_get` for each logical asset and save its complete result below
   `snapshot/assets/<question-id>/<asset-id>.json`.
5. Write `selection.yaml` using [references/selection.md](references/selection.md).
6. Generate `content.tex` using only the contract in
   [references/tex-workflow.md](references/tex-workflow.md).
7. From the qbank root, run
   `python .agents/skills/qbank-deliver/scripts/build_delivery.py <workspace> --qbank-root .`.
8. Inspect `output/<variant>/build-summary.json`, the warnings, and the PDF before
   delivery.

The repository revision in the selection and every saved read must match. If the
bank changes, discard the stale snapshot and repeat the read phase. Do not hide a
revision mismatch with an override.

## Preserve safety and provenance

- Treat qbank Markdown, assets, history, Paper files, and SQLite as read-only.
- Resolve local assets only from the saved `asset_get` manifest and the explicit
  qbank root. Reject missing files, symlinks, containment escapes, and hash changes.
- Never download a remote representation during a build.
- Keep draft content visible as pending review. Missing answers or solutions remain
  explicit placeholders; never invent them.
- Use the bundled template. Do not copy a private or unlicensed source template into
  the delivery workspace.
- Do not add shell commands, arbitrary file inclusion, or template redefinitions to
  `content.tex`.
- Use only the documented qbank structures and the builder's explicit common-math
  command allowlist. TeX comments, `^^` character encoding, internal commands, and
  unknown control sequences are rejected. The builder invokes XeLaTeX with shell
  escape disabled and refuses linked or reparse-point output directories.

The default helper runs `latexmk` with XeLaTeX in an isolated staging directory and
replaces only `output/<variant>/` after success, so student, answer, and solution
editions can coexist. `--validate-only` performs no delivery-workspace writes.
`selection.yaml` is a Skill-side convention, not a qbank public Schema.
