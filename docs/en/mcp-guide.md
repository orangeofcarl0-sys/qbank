# qbank MCP guide

[简体中文](../zh-CN/mcp-guide.md) · [English documentation](README.md) ·
[Codex and MCP integration](codex-integration.md)

## What MCP does in qbank

MCP lets a compatible agent host access a local question bank through typed tools and resources
instead of parsing terminal prose or editing Markdown directly. It is a local STDIO adapter for the
qbank application core, not a remote service, synchronization service, or second bank backend.

- Bank content remains on the local filesystem.
- One MCP process binds to one explicit bank root.
- qbank needs no model API key and does not upload a bank on an agent's behalf.
- Studio, CLI, and MCP share the same Schemas, validation, locks, transactions, history, and index
  policy.
- Skills tell an agent when, why, and under which authority to call tools; MCP executes
  deterministic operations.

![qbank MCP reads and two-phase writes: an agent host calls shared application services over STDIO, and every write prepares before commit](../assets/readme/mcp-operation.en.svg)

## When to use MCP

MCP is appropriate when:

- the agent host supports local STDIO MCP;
- the task needs Schema discovery, question search, typed record reads, or controlled multi-step
  writes;
- tool parameters, results, and errors should be protocol-described instead of inferred from CLI
  text;
- a task spans several calls and needs durable prepare/commit state.

The CLI is simpler when:

- the caller is a shell script, CI job, or one-off batch;
- the host does not support MCP;
- full command help, file pipelines, or interactive terminal work is required.

MCP is optional. CLI, Studio, and repository Skills continue to work when MCP is not installed or
registered.

## Installation and project registration

Install the MCP extra in the same Python environment as qbank:

```powershell
pip install "qbank[mcp]"
```

From the target bank root, preview the configuration change before registration:

```powershell
qbank codex install-mcp --project --dry-run --format json
qbank codex install-mcp --project --yes --format json
qbank codex mcp-check --format json
qbank codex integration-status --format json
```

Registration manages only the marked `qbank-mcp` block in the current bank's
`.codex/config.toml`. It uses the current Python interpreter to run:

```text
python -m qbank mcp --repository <absolute-bank-root>
```

The generated absolute path binds the server to one bank. Do not copy this configuration to another
machine. Rerun the dry-run and installer after moving the bank or changing Python environments. An
unmanaged existing `[mcp_servers.qbank]` causes a conflict instead of being overwritten.

## Tools and resources

### Read tools

| Goal | Tool | Typical use |
| --- | --- | --- |
| Repository health | `repository_status` | Read counts, index state, and `repository_revision` |
| Data contract | `schema_get` | Read Question, Paper, Patch, or Asset Schema |
| Candidate discovery | `question_search` | Text search or typed filters with a bounded result set |
| Full question | `question_get` | Read one authoritative record after its ID is known |
| Validation | `question_validate` | Validate one question or the repository |
| Tags | `taxonomy_get` | Read taxonomy, aliases, and tag definitions |
| Assets | `asset_get` | Read a logical-asset manifest without opening or downloading files |
| Papers | `paper_get` | Read a contained paper definition |
| Operation state | `operation_get` | Inspect prepare, commit, cancel, or post-restart state |
| Paper history | `paper_history_get` | Read append-only paper history |

For broad discovery, call `question_search` first and `question_get` only after an ID is known. This
avoids loading every full body and preserves qbank's index and malformed-source boundaries.

### Resources

MCP exposes eight read-only URIs:

```text
qbank://repository/info
qbank://schema/question
qbank://schema/asset
qbank://schema/paper
qbank://taxonomy
qbank://question/{id}
qbank://paper/{id}
qbank://history/{id}
```

Resources suit display or context attachment by a host; tools suit parameterized search,
validation, and operations. Both call the same application services and are not duplicate stores.

### Write tools

Write capabilities have three groups:

1. `ingest_prepare`, `patch_prepare`, `tag_change_prepare`, `paper_prepare`,
   `asset_ingest_prepare`, `asset_status_prepare`, and `asset_preferred_prepare` prepare changes;
2. `operation_commit` commits an unexpired operation whose repository revision is unchanged;
3. `operation_cancel` explicitly abandons an uncommitted operation.

A prepare result includes at least:

- `operation_id` for later inspection, commit, or cancellation;
- the `repository_revision` observed during preparation;
- an expiry time;
- deterministic diffs, diagnostics, and affected scope;
- confirmation that no authoritative file changed during prepare.

Before commit, inspect the target, diff, warnings, and authorized scope, then pass the original
`repository_revision` to `operation_commit`. If the repository changes between the calls, commit
fails and the caller must reread and prepare again. The revision check must never be bypassed.

## Complete agent flows

### Read-only query

1. Call `repository_status` to confirm the bank and index health.
2. Call `schema_get` to understand fields.
3. Call `question_search` to narrow candidates.
4. Call `question_get` only for selected candidates.
5. Return conclusions with question IDs, provenance, and unresolved facts.

### Structured revision

1. Read the current record with `question_get`.
2. Submit a controlled patch through `patch_prepare`.
3. Present the diff, diagnostics, `operation_id`, and revision.
4. Call `operation_commit` only after explicit authorization.
5. Inspect final state with `operation_get`, then verify with `question_validate`.
6. Call `operation_cancel` when the user rejects the change.

After a lost response, do not create the write again. Inspect the original operation with
`operation_get`; a repeated commit returns the first result without writing twice.

## Status, errors, and recovery

| State or symptom | Meaning | Recovery |
| --- | --- | --- |
| `registered: false` | The bank has no MCP configuration | Repeat registration dry-run and install |
| `sdk_available: false` | The active Python lacks the MCP extra | `pip install "qbank[mcp]"` |
| `codex_cli_available: false` | The external Codex CLI is unavailable | Desktop/IDE hosts may still load project config |
| `DEGRADED` | An optional integration state is missing | Inspect the independent `integration-status` fields |
| revision changed | The bank changed after prepare | Abandon the old operation, reread, and prepare again |
| operation expired | The review window elapsed | Prepare again |
| index dirty/unavailable | Full-text search projection is unavailable | Use CLI: `qbank index rebuild --format json` |
| server response lost | Commit completion is uncertain | Query durable state with `operation_get` |

Structured MCP errors retain stable qbank diagnostic codes. Do not decide whether to retry from
natural-language messages alone; inspect the code, operation state, and repository revision.

## Security boundary

- The STDIO server accepts only the bank root bound at startup and exposes no arbitrary path tool.
- Reads do not create indexes, directories, or dirty markers.
- Prepare calls are read-only and never modify authoritative files.
- Commit rechecks revision, expiry, and input under the repository-wide process lock.
- `.qbank/mcp-operations/` stores only controlled intent and the state required for recovery.
- MCP never launches Ipe, browsers, Studio, or arbitrary local programs.
- External resources are never downloaded automatically.
- Source files outside qbank are read-only by default.
- Unconfirmed answers, provenance, or classification remain `draft`; an agent must not promote
  inference to fact.

## Current limitations

- Only local STDIO transport is provided; there is no HTTP transport, remote hosting, or
  subscription.
- There is no embedded Studio chat, model wrapper, account system, or API-key management.
- qbank generates its own project configuration first; setup templates and interoperability tests
  for more MCP agent hosts remain on the [roadmap](roadmap.md).
- MCP does not perform OCR. Document, image, and PDF digitization will produce reviewable
  candidates before qbank's deterministic import and validation stages.

The machine-authoritative inventory is mirrored in the
[capability matrix](../features/capability-matrix.md). See the
[Codex integration guide](codex-integration.md) for Skills, cross-project authority, and the
separate `$qbank-digitize` role.
