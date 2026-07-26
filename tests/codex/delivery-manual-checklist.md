# qbank-deliver manual test checklist

- [ ] The Skill uses `repository_status`, `question_search`, `question_get`, and
      `asset_get` without adding MCP tools.
- [ ] Selection order equals the Question JSONL snapshot order.
- [ ] Every saved asset manifest belongs to the selected question and logical ID.
- [ ] Local assets are contained, non-symlinked, present, and hash-matched.
- [ ] The agent emits only the documented qbank TeX structures.
- [ ] Student, answer, and solution editions reuse one `content.tex`.
- [ ] Draft and missing-content warnings are visible and no answer is invented.
- [ ] A failed build leaves the last successful output intact.
- [ ] The qbank repository revision and tracked files remain unchanged.
