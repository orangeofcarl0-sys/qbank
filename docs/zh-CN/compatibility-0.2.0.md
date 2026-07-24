# qbank 0.2.0 兼容性基线

[English](../en/compatibility-0.2.0.md) · [中文文档](README.md)

本文冻结 qbank `0.2.0` 的用户可见接口。除阻断性缺陷外，`0.2.0` 不再增加、删除或重命名
下列接口。第三方 Python 模块导入路径不属于本次稳定性承诺。

## 版本矩阵

| 层 | 冻结版本 | 说明 |
| --- | --- | --- |
| qbank 软件包 | `0.2.0` | CLI、Studio、Skill 与 MCP 使用同一安装版本 |
| Question Schema | `1.0` | 题目 Markdown front matter 与交换 JSON |
| Asset Schema | `1.0` | 逻辑资产 manifest 与资产包 |
| Paper Schema | `1.0` | 试卷 YAML |
| Codex integration revision | `3` | 工作流、capability manifest 与上下文交接协议 |
| Python | `>=3.11` | 最低运行时 |

Schema 版本独立于软件包版本。`qbank schema --kind question|paper|patch|asset|asset-package
--format json` 是运行时权威来源。

## CLI 命令

冻结顶层命令：

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

冻结命令组与子命令：

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

参数、退出码和 JSON 字段以 `qbank <command> --help` 及对应 Pydantic 结果模型为准。机器调用
使用 `--format json`，不得解析 Rich 表格。

## MCP STDIO 接口

0.2.0 固定提供 19 个 tools：

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

固定提供 8 个 resource URI/template：

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

`question_search` 只返回索引摘要；完整题目使用 `question_get`。写入采用
`*_prepare → operation_commit` 两阶段协议。prepare 不改权威数据，commit 受 revision、
过期时间和跨进程写锁保护。状态为 `prepared`、`committing`、`committed`、`cancelled` 或
`expired`；重复 commit 返回首次结果。MCP 只支持本地 STDIO。

## Skill capability manifest

Integration revision 3 固定 22 个 capability：

```text
repository_status schema question_search question_get question_validate taxonomy asset paper_get
operation_get paper_history_get ingest_prepare patch_prepare tag_change_prepare paper_prepare
asset_ingest_prepare asset_status_prepare asset_preferred_prepare operation_commit operation_cancel
asset_schema paper_schema question_history
```

仓库级 `$qbank` Skill、初始化资源和运行时 manifest 保持一致。`$qbank-digitize` 是额外领域
工具，不替代 `$qbank` 通信与执行协议。完整映射见[能力矩阵](../features/capability-matrix.md)。

## 稳定诊断代码

0.2.0 固定以下 61 个机器诊断码：

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

CLI 退出码和现有 JSON 键保持兼容。新增诊断上下文可以出现；调用方应按 `code` 判断，不依赖
英文消息全文。

## Studio、CLI 与 MCP 一致性

- `questions/**/*.md` 始终是题目权威数据；
- `.qbank/index.sqlite` 始终是可重建投影；
- CLI、Studio 与 MCP 共用仓库级跨进程锁；
- 权威文件与历史通过可恢复 transaction journal 提交；
- 索引失败不回滚权威 Markdown，而是标记 dirty 并要求 rebuild；
- Studio 不依赖 Codex 服务，Codex/MCP 不依赖 Qt；
- 未安装 `qbank[mcp]` 时 CLI、Studio 与 Skill 仍可工作。

后续版本规则见[兼容性策略](compatibility-policy.md)，运行边界见[已知限制](known-limitations-0.2.0.md)。
