# qbank agent rules

- QBank Studio is the modern presentation adapter in `apps/studio/`, not a separate product or
  repository. Its sidecar lives in `qbank.studio_sidecar` and must reuse qbank application services.
- `qbank desktop` launches QBank Studio Legacy from `qbank.legacy_qt`. Legacy accepts only
  data-loss, security, or severe compatibility fixes.
- Use `python scripts/check.py fast` for ordinary changes, `integration` only for affected
  boundaries, and `release` only for a version freeze or publication.
- Build wheel and Studio artifacts through `python scripts/build.py`; artifacts from one release
  candidate must bind to the same Git commit and dependency locks.
- Markdown under `questions/` is the authoritative question data.
- Before acting across projects, identify the target qbank root, source locations, and
  authorization; run qbank commands with the target root as the working directory.
- Treat non-qbank source projects as read-only unless the user explicitly authorizes writes.
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
- When the project MCP server is available, broad reads use `question_search` before
  `question_get`; every write must use a `*_prepare` tool followed by `operation_commit`.
- Never commit an MCP operation after its `repository_revision` changes. Prepare it again.

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

When maintaining the qbank implementation repository (not ordinary question-bank content),
and the referenced maintenance files are present, apply these rules to every added, changed,
or removed function:

- Read `docs/maintenance-policy.md`, `docs/feature-lifecycle.md`, and
  `docs/documentation-map.md`.
- Create a feature document or equivalent issue summary before implementing new functionality.
- Update the actual affected README, CHANGELOG, user, CLI, Studio, MCP, Skill, manifest,
  configuration, Schema, migration, test, example, screenshot, and limitation documentation.
- Add an ADR when architecture boundaries, authoritative data, transactions, security, or
  dependencies change.
- Run `python scripts/check_docs_sync.py` when the script is present; documentation-sync
  failures block release.
- Keep managed user documentation in both `docs/zh-CN/` and `docs/en/`; update both members of a
  locale pair in the same change and do not mix explanatory Chinese and English prose in one page.
- Keep `v0.2.0` immutable. Put blocking 0.2.x fixes on `release/0.2` for `0.2.1`; put new
  functionality in `0.3.0`. Package and data-Schema versions remain independent.
