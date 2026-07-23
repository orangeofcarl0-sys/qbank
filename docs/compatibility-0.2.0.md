# qbank 0.2.0 兼容性基线

本文冻结 qbank `0.2.0` 的用户可见接口。除阻断性缺陷外，`0.2.0` 不再增加、删除或重命名下列接口。第三方 Python 模块导入路径不属于本次稳定性承诺。

## 版本矩阵

| 层 | 冻结版本 | 说明 |
| --- | --- | --- |
| qbank 软件包 | `0.2.0` | CLI、Studio、Skill 与 MCP 使用同一安装版本 |
| Question Schema | `1.0` | 题目 Markdown front matter 与交换 JSON |
| Asset Schema | `1.0` | 逻辑资产 manifest 与资产包 |
| Paper Schema | `1.0` | 试卷 YAML |
| Codex integration revision | `3` | 工作流、capability manifest 与上下文交接协议 |
| Python | `>=3.11` | 0.2.0 的最低运行时 |

Schema 版本独立于软件包版本。`qbank schema --kind question|paper|patch|asset|asset-package --format json` 是运行时权威来源。

## CLI 命令

冻结的顶层命令为：

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

冻结的命令组及子命令为：

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

各命令的参数、退出码和 JSON 字段以 `qbank <command> --help` 及对应 Pydantic 结果模型为准。机器调用应使用 `--format json`，不得解析 Rich 表格。

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

`question_search` 只返回索引摘要；读取完整题目必须调用 `question_get`。所有写入均采用 `*_prepare → operation_commit` 两阶段协议。prepare 不修改权威数据，commit 受仓库 revision、过期时间和跨进程写锁保护。

Operation 状态固定为：

| 状态 | 含义 |
| --- | --- |
| `prepared` | 已持久化预览，可提交或取消 |
| `committing` | 提交已开始；异常退出后按权威 revision 保守恢复或要求检查 |
| `committed` | 已完成；重复 commit 返回首次结果并标记幂等重放 |
| `cancelled` | 已取消，不可再提交 |
| `expired` | 已过期，不可再提交 |

MCP 只支持本地 STDIO，不提供 HTTP transport、Prompts、订阅或 Studio 内嵌聊天。

## Skill capability manifest

Integration revision 3 固定以下 capability 名称及其访问级别：

| Capability | 访问 | 对应接口 |
| --- | --- | --- |
| `repository_status` | read | CLI status / MCP repository_status / repository resource |
| `schema` | read | CLI schema / MCP schema_get / question schema resource |
| `question_search` | read | CLI search / MCP question_search |
| `question_get` | read | CLI get / MCP question_get / question resource |
| `question_validate` | read | CLI validate / MCP question_validate |
| `taxonomy` | read | CLI tag list / MCP taxonomy_get / taxonomy resource |
| `asset` | read | CLI asset show / MCP asset_get |
| `paper_get` | read | CLI paper validate / MCP paper_get / paper resource |
| `operation_get` | read | MCP operation_get |
| `paper_history_get` | read | MCP paper_history_get |
| `ingest_prepare` | prepare | CLI ingest / MCP ingest_prepare |
| `patch_prepare` | prepare | CLI patch / MCP patch_prepare |
| `tag_change_prepare` | prepare | CLI tag / MCP tag_change_prepare |
| `paper_prepare` | prepare | CLI paper / MCP paper_prepare |
| `asset_ingest_prepare` | prepare | CLI asset ingest / MCP asset_ingest_prepare |
| `asset_status_prepare` | prepare | CLI asset finalize / MCP asset_status_prepare |
| `asset_preferred_prepare` | prepare | CLI asset set-render / MCP asset_preferred_prepare |
| `operation_commit` | write | MCP operation_commit |
| `operation_cancel` | write | MCP operation_cancel |
| `asset_schema` | read | asset schema resource |
| `paper_schema` | read | paper schema resource |
| `question_history` | read | question history resource |

仓库级 `$qbank` Skill、初始化资源和运行时 manifest 必须保持一致。`$qbank-digitize` 是额外的领域引导工具，不替代 `$qbank` 通信与执行协议。

## 稳定诊断代码

0.2.0 固定以下 61 个机器诊断代码：

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

CLI 退出码语义和现有 JSON 键保持兼容。新增诊断上下文可以向后兼容地出现；调用方应按 `code` 判断，不应依赖英文消息全文。

## Studio、CLI 与 MCP 的一致性

三种入口均组合相同的项目上下文、Markdown 仓储、校验器、资产服务、历史存储、事务和索引端口：

- `questions/**/*.md` 始终是题目权威数据；
- `.qbank/index.sqlite` 始终是可重建投影；
- CLI、Studio 和 MCP 写入共享同一个仓库级跨进程锁；
- 权威文件与历史通过可恢复 transaction journal 提交；
- 索引更新失败不回滚权威 Markdown，而是标记 dirty 并要求 rebuild；
- Studio 不依赖 Codex 服务，Codex/MCP 不依赖 Qt；
- 未安装 `qbank[mcp]` 时 CLI、Studio 和 Skill 仍可正常工作。

公共兼容策略的后续版本规则见[兼容性策略](compatibility-policy.md)，0.2.0 的运行边界见[已知限制](known-limitations-0.2.0.md)。
