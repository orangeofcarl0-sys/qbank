# qbank Codex and MCP integration

[简体中文](../zh-CN/codex-integration.md) · [English documentation](README.md)

qbank collaborates with Codex through repository rules, Skills, the local CLI, and an optional
STDIO MCP server. It embeds no chat UI, calls no model SDK, and requires no OpenAI API key. Codex
makes semantic decisions; qbank provides deterministic validation, transactions, and rendering.

In `0.3.0-beta.1`, the CLI, repository Skills, MCP, Studio, and sidecar live in one repository and
reuse the same application services; Studio does not contain a second business implementation.

## Three independent states

| State | Role |
| --- | --- |
| Repository Skill | `.agents/skills/` stored with a bank; supplies the protocol and domain tools |
| User Skill | `$HOME/.agents/skills/`; makes installed Skills discoverable from other projects |
| Codex CLI | Optional external executable; not required for Desktop/IDE repository-Skill discovery |

`codex check` reports `repository_ready`, `codex_cli_ready`, and `degraded` separately. The compatible
`ok` field becomes false only for required repository checks, so `ok: true` does not mean the
external Codex CLI is runnable.

## Two independent Skills

| Skill | Responsible for | Not responsible for |
| --- | --- | --- |
| `$qbank` | Bank location, context, authorization, CLI protocol, validation, and handoff | Choosing fields or taxonomy for a particular digitization project |
| `$qbank-digitize` | PDF/scan interview, field policy, classification tables, sample calibration, and batch acceptance | Writing Markdown directly or reimplementing qbank transactions |

`$qbank-digitize` is an additional domain tool, not a replacement communication protocol. It first
produces a `digitization_decision_packet`. After the user approves field policy and representative
samples, execution returns to `$qbank`.

```powershell
qbank codex install-skill --skill qbank --user --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --dry-run --format json
```

A PDF project therefore confirms bank, sources, and authority; inspects the real Schema, layouts,
and classification table; approves policy and calibration samples; records the decision packet; and
only then uses `$qbank` for Schema reads, dry-runs, committed writes, and validation.

## Cross-project context protocol

A user Skill stores reusable operating rules, not a bank path, task state, or one-time authorization.
Work originating in another project must establish:

- the task objective and observable acceptance criteria;
- a verified target qbank root;
- explicit source files or URLs;
- the selected workflow;
- `read_only`, `dry_run_only`, or `write_authorized` authority;
- unresolved issues that can affect the result.

Run qbank commands with the target bank as the working directory. Source projects are read-only by
default. If the target or write scope is uncertain, stop before mutation rather than inferring from
folder names or old chat context. On handoff, revalidate the root and `integration_revision`.

## Check, install, and update

```powershell
qbank codex check --format json
qbank codex instructions --format markdown
qbank codex integration-status --format json
```

Checks cover `AGENTS.md`, Skill frontmatter, required commands, project/user Skill drift, and one
short Codex CLI probe. A valid but customized or outdated Skill warns and is never overwritten
automatically.

The default installation scope is the same as `--user`. If a different target already exists,
omitting `--update` fails with conflict exit code 5. Preview per-file add/modify/delete changes first:

```powershell
qbank codex install-skill --skill qbank --project --update --dry-run --format json
qbank codex install-skill --skill qbank --project --update
qbank codex install-skill --skill qbank-digitize --user --update --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --update
```

Committed updates stage and atomically switch directories while retaining a backup. Symbolic links
in the source, target, or contained files are rejected. Automation must use `--yes` only after an
outer layer has explicitly authorized the write.

## Data-operation boundary

1. Read the relevant Schema before creating exchange data.
2. Dry-run question, tag, view, paper, and asset writes.
3. Run `qbank validate --format json` after commit.
4. Put temporary AI output in `build/ai/`, generated paper definitions in `papers/generated/`, and final artifacts in `exports/`.
5. Preserve source locations; keep uncertain facts `draft` and never invent answers or provenance.
6. Do not delete or overwrite without explicit authorization.
7. Unattended workflows must not launch `qbank preview --serve` or `qbank desktop`.

Studio and Codex remain modular presentation adapters. The desktop controller does not depend on
Codex services, and Codex services do not depend on Qt.

## Optional local MCP

MCP is a local STDIO adapter bound to one bank. It shares the application core with CLI and Studio,
is not a remote backend, and does not replace the context and authority rules in the Skills. See the
[MCP guide](mcp-guide.md) for setup, the tool and resource catalog, read ordering, two-phase writes,
status diagnostics, and recovery examples.

```powershell
pip install "qbank[mcp]"
qbank codex install-mcp --project --dry-run --format json
qbank codex install-mcp --project --yes --format json
qbank codex mcp-check --format json
```

The project registration writes a managed block in the current bank's `.codex/config.toml` and binds
the server with an absolute `--repository` argument. Every write is split into prepare and commit.
Prepare returns diffs, diagnostics, expiry, and `repository_revision`; commit refuses to run after
the repository changes. Operation state persists under `.qbank/mcp-operations/`, and a repeated
commit returns the first result without writing twice.

Write tools cover question ingestion and patching, tags, papers, asset packages, asset state, and
preferred representations. They never launch Ipe, browsers, or arbitrary local programs. A missing
MCP SDK, registration, or Codex CLI does not impair CLI, Studio, or Skills; `integration-status`
reports `DEGRADED` instead.

qbank currently provides no embedded Studio chat, model API wrapper, resource subscriptions, or
complex prompt-template system.

See the [project roadmap](roadmap.md) for planned agent-host interoperability, an OCR candidate
layer, and the complete digitization workflow. These are future directions, not current-release
capabilities.
