# CLI、Studio、MCP 与 Codex 能力矩阵

本矩阵是 `integration_revision = 3` 的可读镜像。机器权威来源是
`src/qbank/codex_manifest.py`；文档同步门禁验证名称、CLI、MCP tool 和 resource 均在此
出现。

Studio 列现在指 `apps/studio/` 下的现代 QBank Studio。`qbank desktop` 启动
QBank Studio Legacy；Legacy 只作为严重兼容、安全或数据损坏回退，不形成独立能力或
发布路线。两种桌面入口都复用相同 qbank application services。

`0.3.0-beta.2` 冻结值为 Python 包 `0.3.0b2`、Studio Protocol `1.0`，Question、Asset、
Paper Schema `1.0`；本矩阵不引入另一条 Studio 版本线。

| Capability | Workflow | CLI | MCP tool | MCP resource | Access | Studio |
| --- | --- | --- | --- | --- | --- | --- |
| `repository_status` | maintenance | `qbank status` | `repository_status` | `qbank://repository/info` | read | 项目健康状态 |
| `schema` | import | `qbank schema` | `schema_get` | `qbank://schema/question` | read | 不直接显示 |
| `question_search` | select | `qbank search` | `question_search` | — | read | 导航与搜索 |
| `question_get` | select | `qbank get` | `question_get` | `qbank://question/{id}` | read | 编辑器加载 |
| `question_validate` | maintenance | `qbank validate` | `question_validate` | — | read | 保存前后校验 |
| `taxonomy` | taxonomy | `qbank tag list` | `taxonomy_get` | `qbank://taxonomy` | read | 标签面板 |
| `asset` | assets | `qbank asset show` | `asset_get` | — | read | 资源 Inspector |
| `paper_get` | paper | `qbank paper validate` | `paper_get` | `qbank://paper/{id}` | read | 试卷选择 |
| `operation_get` | maintenance | — | `operation_get` | — | read | 不直接暴露 |
| `paper_history_get` | paper | — | `paper_history_get` | — | read | 历史面板 |
| `ingest_prepare` | import | `qbank ingest` | `ingest_prepare` | — | prepare | 不直接暴露 |
| `patch_prepare` | revise | `qbank patch` | `patch_prepare` | — | prepare | 保存预演 |
| `tag_change_prepare` | taxonomy | `qbank tag` | `tag_change_prepare` | — | prepare | 标签修改 |
| `paper_prepare` | paper | `qbank paper` | `paper_prepare` | — | prepare | 试卷修改 |
| `asset_ingest_prepare` | assets | `qbank asset ingest` | `asset_ingest_prepare` | — | prepare | 添加/转换资源 |
| `asset_status_prepare` | assets | `qbank asset finalize` | `asset_status_prepare` | — | prepare | 生命周期操作 |
| `asset_preferred_prepare` | assets | `qbank asset set-render` | `asset_preferred_prepare` | — | prepare | 首选表示 |
| `operation_commit` | maintenance | — | `operation_commit` | — | write | 由应用服务提交 |
| `operation_cancel` | maintenance | — | `operation_cancel` | — | write | 由应用服务取消 |
| `asset_schema` | assets | `qbank schema` | — | `qbank://schema/asset` | read | 不直接显示 |
| `paper_schema` | paper | `qbank schema` | — | `qbank://schema/paper` | read | 不直接显示 |
| `question_history` | revise | — | — | `qbank://history/{id}` | read | 历史面板 |

MCP 另注册 `qbank://schema/question`、`qbank://taxonomy`、
`qbank://repository/info`、`qbank://question/{id}`、`qbank://paper/{id}`、
`qbank://schema/asset`、`qbank://schema/paper` 和 `qbank://history/{id}` 共 8 个资源。
所有 MCP 写操作必须先调用对应 `*_prepare`，检查差异和 `repository_revision`，再调用
`operation_commit`；`operation_cancel` 明确放弃未提交操作。
