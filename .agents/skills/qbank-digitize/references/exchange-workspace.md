# Exchange workspace contract

Use one disposable directory in the source project:

```text
build/digitize/<job-name>/
├─ mineru/
├─ questions.jsonl
├─ assets/
│  └─ packages/
│     └─ <question-id>--<asset-id>.json
└─ review.md
```

Run `python .agents/skills/qbank-digitize/scripts/check_exchange.py <workspace>`
from a Python environment where qbank is installed before any MCP prepare
operation. In the qbank implementation repository, activate `.venv` or invoke its
Python explicitly. The command prints one JSON report and never modifies the
workspace or qbank.

Cross-project local files cannot be passed to the repository-bound MCP server.
Encode binary source material in a package representation's `base64` or `data_uri`
field. Keep HTTP(S) representations as URLs and do not download them automatically.
Path-backed package representations are rejected by this exchange check.

Every question uses logical declarations such as `qbank-asset:figure-1`, and every
logical declaration has exactly one package with the same question and asset ID.
Every package belongs to a question in the same JSONL batch.

`review.md` has this exact header:

```markdown
| Question ID | Source | Page | Issue | Required decision |
| --- | --- | --- | --- | --- |
```

Each following row names a draft question, a stable source, a page or range, one
uncertainty, and one actionable decision. Keep the table empty when no genuine
uncertainty remains.
