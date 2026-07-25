# qbank architecture

## Architectural goals

qbank is a local-first question bank. Markdown files below the configured
`questions` directory are the only authoritative question records. SQLite,
preview pages, exported files, paper artifacts, and history summaries are
derived data. They may be rebuilt or discarded without changing the meaning of
the question bank.

The dependency direction is inward:

```text
presentation (CLI / MCP / Studio / Legacy Qt) -> application -> domain
                              ^
                              |
                  infrastructure adapters
                              ^
                              |
                         bootstrap
```

`bootstrap` is the composition root. It is the only place where application
ports are bound to the Markdown repository, SQLite index, validation, and other
concrete adapters.

The public project map below shows the same boundary using concrete repository
directories and runtime entry points:

![qbank project structure from users and agents through peer presentation adapters and the shared core to authoritative and rebuildable bank data](assets/readme/data-architecture.en.svg)

Skills are guidance artifacts, not runtime data adapters. An agent follows a Skill
and then chooses CLI or MCP; it never reaches the Markdown repository through the
Skill itself. Modern Studio, CLI, MCP, and Legacy are peer adapters, not nested
products or independent backends.

## Layers and responsibilities

### Domain

`qbank.domain`, `qbank.models`, and `qbank.question_layout` define question,
paper, query, result, repository-snapshot, and ordered Markdown field
contracts. The domain does not import Typer, Rich, SQLite, Pandoc, application
services, infrastructure, or CLI modules.

Field names and Markdown sections come from the ordered descriptors in
`qbank.question_layout`. Schema generation, parsing, serialization, patching,
and exchange JSON must use those model/descriptor definitions rather than
duplicate string lists.

### Application

`qbank.application` implements use cases against small protocols. Its public
read service supports:

- `query_questions`
- `get_question`
- `validate_repository`
- `search_questions`
- `rebuild_index`

Application code accepts and returns typed Pydantic/domain objects. It does not
print, import Typer/Rich, execute SQL, open SQLite connections, or parse CLI
arguments.

### Infrastructure

`qbank.infrastructure` binds ports to existing concrete implementations:
Markdown storage, validation rules, and the rebuildable SQLite projection.
Infrastructure may depend on application ports and domain types, but not on
CLI modules. Business invariants remain in domain/application code.

Top-level modules such as `qbank.repository`, `qbank.search_index`, and
`qbank.storage` are retained as compatibility adapters for the 0.x series.
New application and CLI code must not import them directly; the composition
root owns those imports.

Logical assets add a parallel authoritative store below
`assets/<question-id>/<asset-id>/asset.yaml`.  The manifest owns lifecycle,
representation identity, hashes, preference pointers, derivation edges, and
provenance; each local representation is contained in the same directory.
`FileAssetRepository`, `AssetInputAdapter`, `IpeRenderAdapter`, and
`SafeAssetLauncher` are concrete infrastructure adapters.  The application
layer sees only the four small asset ports.  Asset packages are untrusted
exchange input; qbank normalizes them before a single manifest/files/history
transaction and never lets a digitization adapter write an authoritative asset
directory directly.

### Presentation

`qbank.cli`, `qbank.cli_support`, and `qbank.commands` translate flat Typer
arguments into typed requests, call application/use-case APIs, and render
human or JSON output. Commands must not scan Markdown files, execute SQL, or
construct SQLite repositories.

The modern QBank Studio lives under `apps/studio/`. Its Tauri WebView owns only
presentation state and communicates with `qbank.studio_sidecar` through Studio
Protocol v1. The sidecar translates fixed JSON-RPC methods into the same
application services composed by `bootstrap`; it does not define a second
Question model, Schema, lock, transaction, history store, or index.

`qbank.legacy_qt` is the retained QBank Studio Legacy presentation adapter. Its
Qt Widgets shell embeds an offline CodeMirror 6 bundle and a `QWebEngineView`;
narrow `QWebChannel` bridges carry source changes and a closed set of asset
actions. Legacy Qt and the modern Studio share repository formats and
application semantics. Neither has an HTTP backend or desktop-specific
persistence model.

### Bootstrap

`qbank.bootstrap` creates one `ProjectServices` graph per command. The graph
shares a Markdown repository, SQLite adapter, validation adapter, history
store, and sandboxed rendering service across read, mutation, diagnostic, and
artifact use cases. It contains
composition, not business decisions. Top-level Python compatibility adapters
may construct defaults locally, but CLI paths must use the composition root.

## Data ownership and projections

- Markdown question sources are canonical.
- `qbank.yaml` is canonical project configuration.
- SQLite is a disposable search projection. A missing, corrupt, stale, or
  dirty index is never silently recreated by a read operation.
- History is committed with authoritative Markdown mutations.
- Preview, export, and paper outputs consume already-selected typed questions;
  exporters do not query repositories.
- Package resources are authoritative only for initializing new projects.
  Existing project templates remain user-owned.

## Transactions and failures

Question mutations validate and plan all authoritative changes before commit.
Markdown and history are committed as one transaction. Index synchronization
runs afterward: a failure leaves Markdown committed, writes the dirty marker,
and reports a warning. Index rebuild uses a temporary database followed by an
atomic replacement.

Every CLI, Studio, MCP, asset, tag, paper, saved-view, index-rebuild, and Codex
configuration write uses the same repository-wide lock service. A kernel byte
lock provides cross-process ownership on Windows and POSIX; a JSON sidecar is
diagnostic metadata only. The protected interval includes the final repository
revision check, authoritative transaction, history write, and index update.
Same-thread nested application services reuse the existing lease.

MCP prepare/commit/cancel operations are durable state machines stored below
`.qbank/mcp-operations/`. The operation store holds only the typed intent,
revision, lifecycle state, and first commit result needed for restart recovery;
it does not duplicate full repository snapshots. A commit verifies expiry and
the cryptographic repository revision while holding the shared lock. Response
loss is handled by returning the recorded first result, while an interrupted
`committing` state with a changed repository is rejected for explicit
inspection.

Export and paper artifacts use the same rollback-capable commit primitive for
the primary output and copied local resources. Optional dependencies, output
conflicts, and validation are checked before any destination write. DOCX is
generated in a temporary directory and committed only after Pandoc succeeds.

Read-only commands do not create `.qbank`, databases, schemas, or dirty
markers. Search fails with exit code 3 when the enabled index is unavailable or
dirty and instructs the caller to run `qbank index rebuild`.

Asset mutations follow the same safety posture: replacements are hash-versioned
and append-only, rendering stages external-tool output before committing it,
and every local launch is restricted to a representation registered in the
manifest.  `qbank preview --serve` is a local-only presentation adapter bound
to `127.0.0.1`; it has a per-process capability token and same-origin check,
and delegates each fixed operation to the application service rather than
accepting paths or command strings from a browser.

Desktop image bindings use the stable `qbank-asset:<asset-id>` form (with
legacy `asset:` accepted) and the TeX command `\qbankasset{<asset-id>}`.
Unregistered legacy paths receive deterministic preview bindings and are
materialized only when the user requests a mutation. Ipe editing creates a
versioned working representation; a saved hash change marks derived renders
stale. Rerendering, preferred-representation changes, restore, and finalization
remain explicit application operations.

## Enforced boundaries

`lint-imports` executes the dependency contracts in `pyproject.toml`. Pyright,
Ruff complexity limits, the AST cycle test, deptry, and branch-coverage gates
are complementary controls. Architecture changes must update this document,
an ADR when the decision is durable, and the executable contracts in the same
change.

The repository uses native Python, npm, and Cargo tools rather than a monorepo
framework. `scripts/change-impact.json` selects fast or integration checks, and
`scripts/build.py` binds the Python wheel, bundled sidecar, Studio installer,
and portable archive to one Git commit and the three dependency locks.

## Extension seams

The internal protocols are testing and composition seams, not a public plugin
system. New exporters register a typed exporter in the export registry. A new
index backend implements the read, mutation, and health ports and is wired in
bootstrap. An MCP adapter should call `QuestionService` and typed use cases,
never CLI parsing. None of these extensions should require changes to the
canonical Markdown codec, repository scanning, query filtering, or validation
rules.
