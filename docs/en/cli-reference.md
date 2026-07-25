# CLI command reference

[简体中文](../zh-CN/cli-reference.md) · [English documentation](README.md)

This page lists the qbank `0.3.0-beta.1` public command entry points. This beta retains the
documented 0.2.0 command names. Each command's `--help`, the
[current compatibility matrix](compatibility-0.3.0-beta.1.md), and the
[0.2.0 baseline](compatibility-0.2.0.md) define options, defaults, and exit codes.

## Project, diagnostics, and index

| Command | Purpose |
| --- | --- |
| `qbank init` | Initialize a bank; conflicts cause zero writes |
| `qbank status` | Summarize bank, validation, and index state |
| `qbank doctor` | Check configuration, tools, Schemas, and index health |
| `qbank schema` | Emit Question, Paper, Patch, or Asset Schemas |
| `qbank index rebuild` | Atomically rebuild the SQLite search projection |
| `qbank preview` | Build static preview; `--serve` is interactive only |
| `qbank desktop` | Start the optional Studio desktop editor |

## Questions and retrieval

| Command | Purpose |
| --- | --- |
| `qbank add` | Add one question |
| `qbank ingest` | Import JSON or JSONL batches |
| `qbank patch` | Apply a structured question revision |
| `qbank delete` | Delete a question and its authoritative history |
| `qbank validate` | Validate all questions or one selected question |
| `qbank list` | List questions |
| `qbank query` | Run a structured-filter query |
| `qbank search` | Full-text search through the read-only SQLite index |
| `qbank get` | Read a complete question |
| `qbank export` | Export a question collection |

## Tags and saved views

| Command | Purpose |
| --- | --- |
| `qbank tag list` | List tags |
| `qbank tag show` | Show a tag and related questions |
| `qbank tag stats` | Report tag statistics |
| `qbank tag cooccur` | Calculate tag co-occurrence |
| `qbank tag rename` | Rename a tag |
| `qbank tag merge` | Merge tags |
| `qbank tag normalize` | Normalize tags |
| `qbank tag delete` | Delete tag references |
| `qbank view list` | List saved views |
| `qbank view apply` | Apply a saved view |
| `qbank view save` | Save a query snapshot |
| `qbank view rename` | Rename a saved view |
| `qbank view delete` | Delete a saved view |

## Assets

| Command | Purpose |
| --- | --- |
| `qbank asset list` | List assets for a question |
| `qbank asset show` | Show a logical asset and its representations |
| `qbank asset validate` | Validate resource boundaries and lifecycle |
| `qbank asset add` | Add a managed resource |
| `qbank asset ingest` | Import a logical asset package |
| `qbank asset replace` | Append a replacement representation |
| `qbank asset normalize` | Convert a legacy path to a logical asset |
| `qbank asset finalize` | Update asset lifecycle state |
| `qbank asset set-render` | Select the preferred render representation |
| `qbank asset set-editor` | Select the preferred editable representation |
| `qbank asset render` | Render from an editable source |
| `qbank asset edit` | Start the configured interactive editor |
| `qbank asset open` | Open a resource with the operating system |

Unattended automation must not silently start `asset edit`, `asset open`, or `preview --serve`.

## Papers

| Command | Purpose |
| --- | --- |
| `qbank paper validate` | Validate a paper definition and question references |
| `qbank paper build` | Build student, answer, or solution variants |

## Codex and MCP

| Command | Purpose |
| --- | --- |
| `qbank codex check` | Check repository, Skill, and Codex CLI readiness |
| `qbank codex instructions` | Emit integration rules and workflows |
| `qbank codex integration-status` | Summarize Skill and MCP states |
| `qbank codex install-skill` | Preview or install a project/user Skill |
| `qbank codex install-mcp` | Preview or register the local project MCP server |
| `qbank codex uninstall-mcp` | Preview or remove project MCP registration |
| `qbank codex mcp-check` | Check MCP installation and configuration |
| `qbank mcp` | Start the local STDIO MCP Server |

Run any command that may write configuration or bank data with `--dry-run` first. For machine
consumption, use `--format json` and interpret both exit codes and stable diagnostic codes.
