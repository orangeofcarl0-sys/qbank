# Changelog

## Unreleased

- Added separate Simplified Chinese and English README and user-documentation trees, stable
  language-selection pages for existing links, and a localization policy that prevents mixed prose.
- Extended the documentation gate to require locale pairs, cross-language navigation, language
  separation, bilingual CLI coverage, synchronized changes, and executable examples in both READMEs.
- Established a documentation lifecycle, ownership map, feature template, CLI/capability
  references, contribution guide, security policy, and ADR requirement for changes to
  architecture, authoritative data, transactions, security, or dependencies.
- Added a deterministic documentation synchronization gate covering CLI, MCP, Codex Skill,
  capability manifest, README examples, public-data safety, compatibility notes, and
  user-facing CHANGELOG coverage.
- Defined immutable `v0.2.0`, `release/0.2` patch maintenance, and `0.3.0` feature-development
  rules without changing runtime behavior, data formats, or Schema versions.

## 0.2.0 - 2026-07-23

- Added one repository-wide, cross-process write lock shared by CLI, Studio, and MCP
  mutations, with bounded waits, holder diagnostics, Windows support, and crash recovery.
- Persisted MCP prepare/commit/cancel state below `.qbank/mcp-operations/` so reviewed
  operations and their first commit responses survive STDIO server restarts.
- Added safe MCP asset-package, lifecycle-status, and preferred-representation mutations;
  no MCP asset operation launches an editor or arbitrary local program.
- Moved paper persistence into a shared application service with revision checks,
  transactional paper history, and the same repository lock.
- Added stable lock, revision, operation-lifecycle, and Schema error codes across CLI and
  MCP, plus real Codex STDIO and isolated wheel verification helpers.
- Removed redundant full-repository hashes from MCP prepare/commit while retaining the
  initial/final revision checks and shared-lock safety boundary.
- Made healthy search and structured MCP query read summary rows from SQLite, while a
  content revision detects external Markdown changes and `question_get` remains the only
  full-question retrieval path.
- Added recoverable mutation journals around authoritative file/history replacement and
  hardened Windows containment against UNC, junction, reparse-point, and path-replacement
  escapes without relying on symbolic-link privileges.
- Made Codex discovery probe every supported CLI candidate, retain per-candidate version or
  failure details, and select a runnable npm/PATH entry when a Store alias is denied.
- Added doctor warnings for network or synchronized filesystems and documented that 0.2.0
  does not promise multi-machine shared-repository locking.
- Kept question, asset, paper, taxonomy, and view Schema version `1.0` independent from
  the Python package version.
- Frozen the 0.2.0 CLI, 19 MCP tools, 8 MCP resources, operation states, diagnostic codes,
  and integration-revision-3 capability manifest in dedicated compatibility documentation.

## 0.1.0 - 2026-07-23

- Frozen the first private release baseline and completed the README with explicit product
  boundaries, Studio/CLI/Codex entry points, installation paths, artifact verification, and
  compatibility expectations.

- Added repository-scoped OSS readiness, release preparation, approval-gated GitHub publishing,
  and thin open-source orchestration Skills with deterministic, redacted reports.
- Added isolated wheel/sdist construction, installed-artifact smoke tests, archive manifests,
  SHA-256 checksums, release-plan generation, and a fully self-authored public demo bank.
- Documented public-release safety rules and made all remote repository, push, tag, and Release
  operations require a reviewed prepare plan plus explicit user confirmation.
- Made Codex readiness explicit and fast with in-process command discovery, project/user
  Skill drift checks, structured workflows, and separate repository, CLI, and degraded
  states while preserving the existing `ok`, checks, and command-sequence fields.
- Added an optional repository-bound STDIO MCP Server with typed read tools and resources,
  revision-checked prepare/commit mutations, idempotent commits, and dry-run-first project
  registration that leaves CLI and Studio usable without the MCP SDK.
- Added a versioned Codex context and handoff protocol for cross-project work, with an
  explicit target root, source locations, authorization boundary, acceptance criteria,
  deterministic bootstrap, and verifiable completion record.
- Added the separate `$qbank-digitize` domain Skill for research-first PDF project
  interviews, selective field policies, classification-table normalization, sample
  calibration, and explicit handoff back to the unchanged `$qbank` execution protocol.
- Added dry-run-first project and user Skill updates with deterministic file diffs,
  explicit authorization, atomic replacement, retained backups, JSON output, and rollback
  that preserves the original commit error.
- Hardened CLI preflight validation so unsupported output formats are zero-write,
  accepted UTF-8 BOM exchange files from Windows PowerShell, removed the private
  Typer API dependency, and normalized optional Qt load failures to exit code 7.
- Moved Studio question, project-status, and paper workflows behind a typed project
  port shared with the CLI mutation layer, and split core versus Qt development
  dependencies so CLI tests remain runnable without a working desktop runtime.
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
- Added rebuildable SQLite tag-count/co-occurrence projections, alias-safe saved views,
  native synonym confirmation, and themed readable Top-N table headers.
- Fixed Studio filter clearing and saved-view snapshot semantics so visible chips are
  authoritative, query transitions refresh once, combined chips wrap in the compact
  navigation column, and out-of-result open questions are identified explicitly.
- Added an explicit project and paper context workflow, transactional question
  create/copy/import/delete actions, editable source provenance, and a unified question
  and asset history timeline. Studio saves now commit Markdown, pending taxonomy, and
  history together, while background SQLite searches discard stale generations.
- Separated the open editor identity from explicit multi-selection, simplified the
  default navigation surface, completed subject/language and enum facet restoration,
  and replaced ambiguous tag cycling with accessible include/exclude/clear controls.
- Slimmed Studio to a fixed-height single-row toolbar with compact project health,
  paper, syntax, workspace, and editor actions; added a native persistent settings
  window for theme, default view, detail-drawer, and optional project-path preferences.

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
