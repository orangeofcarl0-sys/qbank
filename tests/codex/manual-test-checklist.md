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

Record the Codex version, prompt, exit status, observed Skill discovery, commands executed,
and any deviations for each manual run.

If `codex --help` or `codex exec --help` cannot start, record the executable path and exact
launch error, leave the discovery items unchecked, and use the repository fixtures for
manual validation. Do not treat a PATH entry alone as a successful discovery run.
