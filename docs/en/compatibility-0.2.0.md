# qbank 0.2.0 compatibility reference

[简体中文](../zh-CN/compatibility-0.2.0.md) · [English documentation](README.md)

This page records the user-visible qbank `0.2.0` interfaces as released. That line accepts only
security, data-loss, and blocking compatibility fixes; it does not add, remove, or rename the
interfaces below. Third-party Python import paths are outside this stability commitment.

## Version matrix

| Layer | Recorded 0.2.0 value | Meaning |
| --- | --- | --- |
| qbank package | `0.2.0` | CLI, Studio, Skills, and MCP use one installed version |
| Question Schema | `1.0` | Question Markdown front matter and exchange JSON |
| Asset Schema | `1.0` | Logical-asset manifest and asset package |
| Paper Schema | `1.0` | Paper YAML |
| Codex integration revision | `3` | Workflows, capability manifest, and context handoff |
| Python | `>=3.11` | Minimum runtime |

Schema versions are independent from the package version. The runtime authority is
`qbank schema --kind question|paper|patch|asset|asset-package --format json`.

## CLI commands

0.2.0 top-level commands:

```text
qbank init
qbank status
qbank doctor
qbank schema
qbank add
qbank ingest
qbank validate
qbank list
qbank get
qbank query
qbank search
qbank patch
qbank delete
qbank desktop
qbank mcp
qbank preview
qbank export
```

0.2.0 command groups and subcommands:

```text
qbank index rebuild
qbank paper validate
qbank paper build
qbank codex check
qbank codex instructions
qbank codex install-skill
qbank codex mcp-check
qbank codex install-mcp
qbank codex uninstall-mcp
qbank codex integration-status
qbank asset list
qbank asset show
qbank asset ingest
qbank asset add
qbank asset open
qbank asset edit
qbank asset render
qbank asset replace
qbank asset set-render
qbank asset set-editor
qbank asset finalize
qbank asset normalize
qbank asset validate
qbank tag list
qbank tag show
qbank tag rename
qbank tag merge
qbank tag delete
qbank tag normalize
qbank tag stats
qbank tag cooccur
qbank view list
qbank view save
qbank view apply
qbank view rename
qbank view delete
```

`qbank <command> --help` and the corresponding Pydantic result models define options, exit codes,
and JSON fields. Machine clients use `--format json` and do not parse Rich tables.

## MCP STDIO interface

Release 0.2.0 provides exactly 19 tools:

```text
repository_status
schema_get
question_search
question_get
question_validate
taxonomy_get
asset_get
paper_get
operation_get
paper_history_get
ingest_prepare
patch_prepare
tag_change_prepare
paper_prepare
asset_ingest_prepare
asset_status_prepare
asset_preferred_prepare
operation_commit
operation_cancel
```

It provides exactly 8 resource URIs/templates:

```text
qbank://repository/info
qbank://schema/question
qbank://question/{id}
qbank://taxonomy
qbank://paper/{id}
qbank://schema/asset
qbank://schema/paper
qbank://history/{id}
```

`question_search` returns index summaries; complete content requires `question_get`. Writes use the
two-stage `*_prepare → operation_commit` protocol. Prepare does not modify authority; commit checks
revision, expiry, and the cross-process write lock. Operation states are `prepared`, `committing`,
`committed`, `cancelled`, and `expired`; repeated commit returns the first result. Only local STDIO
transport is supported.

## Skill capability manifest

Integration revision 3 freezes 22 capability names:

```text
repository_status schema question_search question_get question_validate taxonomy asset paper_get
operation_get paper_history_get ingest_prepare patch_prepare tag_change_prepare paper_prepare
asset_ingest_prepare asset_status_prepare asset_preferred_prepare operation_commit operation_cancel
asset_schema paper_schema question_history
```

The repository `$qbank` Skill, initialization resources, and runtime manifest remain synchronized.
`$qbank-digitize` is an additional domain guide and does not replace the `$qbank` execution protocol.
See the [capability matrix](../features/capability-matrix.md) for the full mapping.

## Stable diagnostic codes

Release 0.2.0 freezes these 61 machine diagnostic codes:

```text
asset_missing asset_command_failed asset_command_rejected asset_conflict
asset_derivation_invalid asset_failed asset_hash_mismatch asset_manifest_invalid
asset_needs_redraw asset_not_found asset_outside_assets asset_package_invalid
asset_path_escape asset_representation_missing asset_render_stale cli_usage conflict
content_in_yaml deprecated_question dependency_missing general_error duplicate_batch_id
duplicate_id duplicate_question duplicate_section empty_stem external_asset
filename_id_mismatch index_dirty index_disabled index_stale index_unavailable
data_validation export_failed invalid_filter invalid_json invalid_encoding
invalid_resource_uri invalid_source_file invalid_timestamp ipe_unavailable
latex_brace_unbalanced latex_delimiter_unbalanced latex_dollar_unbalanced
missing_options missing_question missing_reviewed_answer model_validation
multiple_choice_answer_format question_not_found project_not_found repository_locked
repository_revision_changed operation_expired operation_cancelled
operation_already_committed schema_validation_failed single_choice_answer_mismatch
total_score_mismatch undeclared_asset_reference unused_asset
```

CLI exit semantics and existing JSON keys remain compatible. Additional diagnostic context may be
added; clients match `code`, not the complete English message.

## Studio, CLI, and MCP consistency

- `questions/**/*.md` is always authoritative question data.
- `.qbank/index.sqlite` is always a rebuildable projection.
- CLI, Studio, and MCP share one repository-level cross-process write lock.
- Authority and history use a recoverable transaction journal.
- Index failure does not roll back Markdown; it marks the index dirty and requires rebuild.
- Studio does not depend on Codex services, and Codex/MCP does not depend on Qt.
- CLI, Studio, and Skills work without `qbank[mcp]`.

See the [compatibility policy](compatibility-policy.md) for later release rules and
[known limitations](known-limitations-0.2.0.md) for runtime boundaries.
