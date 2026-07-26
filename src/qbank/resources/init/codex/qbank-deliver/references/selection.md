# Selection contract

`selection.yaml` is a versioned project-side contract. It does not extend the
Question, Asset, or Paper Schema.

```yaml
version: "1"
repository_revision: "sha256:..."
template: "qbank-zh-exam-v1"
variant: "student"
document:
  title: "合成示例试卷"
  subject: "示例学科"
  date: "2026-07-26"
  duration_minutes: 120
questions:
  - id: "DEMO-MATH-0001"
    score: 10
    assets: {}
  - id: "DEMO-FIG-0001"
    score: 15
    assets:
      figure-1: "render-png"
```

Rules:

- `version` is exactly `"1"` and `template` is `qbank-zh-exam-v1`.
- `variant` is `student`, `answer`, or `solution`.
- `repository_revision` equals the revision used for every saved MCP read.
- `document.title` is required. Subject and date are optional;
  `duration_minutes`, when present, is a positive integer.
- Questions are unique and ordered. Every score is positive.
- Each asset mapping selects one representation returned by `asset_get`.
- Selection criteria and exclusions may be documented beside the contract, but
  hidden filters never change the ordered list.

The builder warns and continues for draft questions. Answer and solution editions
also warn when their required content is absent and render `未提供`.
