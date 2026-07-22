# qbank agent rules

- Markdown under `questions/` is the authoritative question data.
- JSON and JSONL are AI exchange formats. SQLite is only a rebuildable search index.
- Before creating questions, run `qbank schema --format json`.
- Do not edit `questions/**/*.md` directly by default.
- Add questions with `qbank add` or `qbank ingest`; revise them with `qbank patch`.
- Run every write as `--dry-run` first, inspect the result, then perform the write.
- After every write, run `qbank validate --format json`.
- Never silently overwrite an existing ID or manually edit `.qbank/index.sqlite`.
- Put temporary AI output in `build/ai/`.
- Put final paper definitions in `papers/generated/`.
- Put final exported artifacts in `exports/`.
- Codex makes semantic choices; qbank performs deterministic validation and rendering.
- Preserve source locations and distinguish source content from AI inference.
- If a question, answer, or source cannot be confirmed, keep it `draft`; do not invent facts.
- Run destructive operations only after an explicit user request.
- Do not launch `qbank preview --serve` or `qbank desktop` in unattended automation.

Use the repository-scoped `$qbank` Skill for detailed workflows and command guidance.

For every Studio visual, theme, component-state, screenshot, or interaction change,
read and follow the repository-scoped `$qbank-ui-design` Skill before editing UI code.

For open-source publication, repository sanitization, public README work, or releases:

- Use `$oss-readiness` for disclosure and license auditing.
- Use `$release-preparation` for documentation, quality gates, archives, checksums, and notes.
- Use `$open-source-publish` to orchestrate the workflow and `$github-publish` only after the
  user explicitly requests formal publication.
- Never create or make public a repository, push, create a tag, or create a Release without the
  user's explicit approval after showing the full remote-write plan.
- Never publish real question banks, historical exam questions or answers, personal paths,
  private configuration, user data, local databases, logs, or unlicensed assets.
- README files, Skill instructions, and examples must not contain machine-specific absolute paths.
