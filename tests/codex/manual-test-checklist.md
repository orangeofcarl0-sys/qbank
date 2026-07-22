# Manual Codex Skill test checklist

- [ ] Codex discovers and explicitly acknowledges `$qbank`.
- [ ] Codex reads the question Schema before creating exchange data.
- [ ] Codex uses JSON output for machine-facing commands.
- [ ] Codex dry-runs every proposed write.
- [ ] Codex does not directly edit `questions/**/*.md`.
- [ ] Codex runs `qbank validate --format json` after a real write.
- [ ] Codex can generate and validate `papers/generated/<name>.yaml`.
- [ ] Temporary AI data is written under `build/ai/`.
- [ ] Final artifacts are written under `exports/`.
- [ ] Uncertain questions stay `draft` without invented answers or sources.
- [ ] Cross-project work records the target qbank root, source locations, workflow,
      authorization, acceptance criteria, and unresolved questions.
- [ ] qbank commands use the target root as their working directory.
- [ ] A non-qbank source project remains read-only without separate explicit authorization.
- [ ] Missing target or write scope causes a focused question before any mutation.
- [ ] A resumed task verifies the target root and `integration_revision` before writing.
- [ ] Completion reports commands, writes, validation, outputs, warnings, and one next step.

Record the Codex version, prompt, exit status, observed Skill discovery, commands executed,
and any deviations for each manual run.

If `codex --help` or `codex exec --help` cannot start, record the executable path and exact
launch error, leave the discovery items unchecked, and use the repository fixtures for
manual validation. Do not treat a PATH entry alone as a successful discovery run.
