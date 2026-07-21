# Changelog

## 0.1.0 - 2026-07-18

- Added project-level `taxonomy.yaml` metadata while keeping question Markdown
  `topics` as the sole tag-relation authority, plus persistent `views.yaml` query views.
- Added atomic `qbank tag` rename, merge, delete, normalize, statistics, and
  co-occurrence commands, durable history/undo data, and `qbank view` lifecycle commands.
- Added Studio tag facets with include/exclude and AND/OR composition, field facets,
  removable filter chips, saved-view editing, multi-question topic changes, and
  registry-aware Inspector autocomplete with pending/synonym guidance.
- Added a native tag manager with impact previews and a lightweight tag overview with
  frequency bars, Top-N co-occurrence, year coverage, and chapter coverage; chart clicks
  now produce real main-window filters without adding a dashboard or graph database.

- Modernized Studio with centralized light/dark design tokens shared by Qt,
  CodeMirror, and Markdown/MathJax, plus a maintained component gallery and
  repository-scoped `$qbank-ui-design` workflow.
- Fixed repeated live theme switching so CodeMirror backgrounds, gutters,
  selections, cursors, search surfaces, and native web-view color schemes follow
  the Qt shell in both directions.
- Rebuilt the Studio question-detail drawer as a compact, resizable Inspector with
  localized properties, topic tags, fixed dirty actions, asset cards, structured
  provenance, history timelines, actionable empty states, and legacy-image
  normalization controls.
- Hardened Studio asset operations with typed capabilities, containment-safe previews,
  native save/discard/cancel gating, compensating rollback for failed declarations,
  explicit external/invalid states, and deterministic provenance/history display.
- Normalized native Studio typography to scalable Qt point sizes, eliminating invalid
  `QFont` point-size warnings while preserving the existing Windows visual density.
- Refined the question-detail drawer into a stacked, accessible property
  inspector with custom single-surface combo boxes and borderless spin controls,
  and made the preview image-drop guidance responsive without overlaying document
  content.
- Fixed saved-snapshot dirty tracking, stable all-questions navigation, stale
  preview replacement, native image-menu dismissal, and accessible native
  confirmation dialogs; added QtAwesome as the sole UI icon dependency.
- Added the optional PySide6 desktop editor with Zotero-style navigation,
  embedded CodeMirror 6 Markdown/TeX editing, live MathJax preview, and a
  collapsible metadata/assets/source/history drawer.
- Added stable `qbank-asset:` and `\qbankasset{}` references, deterministic
  bindings for legacy paths, and eight fixed image context actions.
- Added versioned Ipe edit sessions, saved-file reconciliation, stale render
  tracking, explicit rerendering, preferred-representation selection, and
  non-destructive restore/history workflows.
- Added native logical multi-representation assets, authoritative `asset.yaml`
  manifests, package exchange schemas, lifecycle/history validation, immutable
  replacement and Ipe PDF/SVG/PNG rendering commands.
- Added `qbank asset` management commands and a token-protected,
  `127.0.0.1`-only `qbank preview --serve` management page.
- Added the asset-package boundary for the Zhejiang University 841 Ipe
  digitization workflow; it emits packages rather than writing qbank asset
  directories directly.
- Paper builds now copy only assets referenced by the selected student or
  answer content, preventing answer-only figures from entering student
  artifact manifests.

- Initial local-first Markdown question bank CLI.
- Added JSON/JSONL import, validation, structured patching, history, querying, FTS5
  search, static preview, exports, and Markdown/HTML/DOCX paper builds.
- Added machine-readable schemas, eight sample questions, documentation, and tests.
- Hardened configured-path containment, fail-closed initialization, malformed-source
  protection, and rollback-capable source/history transactions.
- Added strict Markdown image diagnostics, sandboxed Jinja HTML rendering, atomic
  preview replacement, and two-character SQLite search fallback.
- Added line-aware JSONL recovery, durable dirty-index reporting, paper/patch schemas,
  tri-state paper flags, strict timestamps and query filters, and expanded doctor/status
  diagnostics.
- Added immutable project contexts, single-pass repository snapshots, typed application
  results, named mutation plans, and small repository/index/history/rendering ports.
- Split SQLite into explicit read-only and writable modes and centralized all schema,
  writes, searches, and stale checks on one `IndexDocument` projection.
- Unified Markdown image handling and sandboxed rendering through shared asset/render
  services; moved initialization and preview templates into packaged resources.
- Split the CLI into project, question, and artifact command modules; added strict
  Pyright, complexity limits, import-graph checks, wheel-resource tests, and documented
  internal dependency boundaries.
- Added repository `AGENTS.md`, the discoverable `$qbank` Skill and workflow references,
  Codex discovery fixtures, and packaged integration files for newly initialized banks.
- Added `qbank codex check`, `qbank codex instructions`, and confirmation-gated
  `qbank codex install-skill`, backed by a reusable service layer for a future MCP wrapper.
- Added explicit domain/application/infrastructure boundaries, a centralized composition
  root, a reusable `QuestionService`, executable Import Linter contracts, deptry, and
  branch-coverage quality gates.
- Added architecture, review, compatibility, and ADR documentation plus lossless
  JSON/Markdown round-trip and in-memory port probes.
- Added the registry-based `txt` question exporter without changing repository, parser,
  query, or validation internals.
- Centralized diagnostic codes and JSON failure envelopes, including pre-dispatch CLI
  usage errors and unavailable-index states.
- Completed composition-root injection for mutations, diagnostics, and rendering,
  removed the unused parallel ports module, and reduced legacy storage APIs to
  repository wrappers.
- Made exports and paper artifacts rollback-capable with dependency preflight and
  zero-partial-output failure behavior.
- Locked build tooling alongside runtime/development dependencies, exercised installed
  wheel entry points, and hardened the branch-coverage report gate against empty input.
