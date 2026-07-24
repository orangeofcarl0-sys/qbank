# qbank 0.2.0 known limitations

[简体中文](../zh-CN/known-limitations-0.2.0.md) · [English documentation](README.md)

These are known support boundaries in the frozen 0.2.0 release, not implicit capabilities or
untriaged P0/P1 blockers.

## Filesystems and concurrency

- The primary supported deployment is one bank workspace on a conventional local filesystem.
- `qbank doctor` warns for UNC paths, network drives, NFS/SMB/CIFS, cloud-sync directories, and
  filesystems with uncertain lock semantics.
- The repository lock coordinates CLI, Studio, and MCP processes that follow the qbank protocol. It
  cannot stop other editors or synchronization software from changing files directly.
- Concurrent writes from multiple computers to one network-shared bank are not safety-guaranteed.
- Windows containment resolves paths and rejects junction, symbolic-link, and other reparse-point
  escapes.

## Transactions and external modification

- Writes use same-directory temporary files, a repository lock, and `.qbank/transactions/` journals.
  The next write recovers an unfinished prepared transaction or cleans a committed journal.
- After a lost MCP response, the persisted operation can return the original result. In the narrow
  crash window where authority changed but operation completion was not recorded, replay is
  conservatively refused pending revision inspection.
- Revisions are recomputed at critical boundaries rather than held in a long-lived cache. qbank does
  not promise protection against a malicious process with write access racing within one atomic
  replacement system call.

## Performance

- Healthy `search` and structured MCP queries read SQLite summaries; only `question_get` reads a
  complete question.
- Search still computes a byte-level content revision to detect external Markdown edits. Its cost is
  proportional to total question-Markdown bytes, not result count.
- `index rebuild` parses every question and rebuilds trigram FTS, making it the most expensive
  maintenance operation on a large bank.
- Batch prepare/commit costs are dominated by full Markdown parsing, Pydantic validation, and
  deterministic revision checks.
- Release 0.2.0 has no resident file watcher or unsafe process-local source cache.

## Optional dependencies and rendering

- Studio requires `qbank[desktop]`; the core CLI installation does not include Qt.
- Local STDIO MCP requires `qbank[mcp]`; its absence does not affect CLI, Studio, or Skills.
- DOCX requires external Pandoc. Markdown, HTML, and JSON remain available without it.
- Formula preview uses the MathJax CDN by default and may show TeX source while fully offline.
- Raw HTML is disabled. Remote images are allowed with warnings and never downloaded automatically.
- Ipe editing and rendering require a local Ipe installation. Ordinary PNG resources do not expose
  unsupported Ipe actions.

## Codex integration and product scope

- Repository Skill, user Skill, and Codex CLI are independent states; `ok: true` does not imply a
  runnable Codex CLI.
- qbank provides no model SDK, API-key management, embedded Studio chat, MCP HTTP transport,
  Prompts, or subscriptions.
- qbank does not provide OCR, automatic scan segmentation, answer inference, online examinations,
  or automatic paper-selection algorithms.
- `$qbank-digitize` helps define digitization rules and calibration samples, but users remain
  responsible for facts, classification choices, and final authorization.
- Third-party Python APIs are not frozen. The stable boundary is the CLI, Schema, Markdown, JSON,
  Skill, and MCP contract in the [compatibility baseline](compatibility-0.2.0.md).
