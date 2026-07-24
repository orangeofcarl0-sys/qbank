# ADR 0004: Documentation is a release gate

- Status: Accepted
- Date: 2026-07-24

## Context

qbank 同时提供 CLI、Studio、Codex Skill 和 MCP。单独维护各入口会导致命令、能力、
Schema、失败行为和用户文档漂移。仅依靠发布前人工检查不能稳定发现“代码已经提供能力，
但用户文档、兼容性说明或 Skill 未更新”的情况。

## Decision

文档被视为公共产品契约。新增、修改或删除功能必须遵循统一功能生命周期，并运行
`scripts/check_docs_sync.py`。该门禁校验 capability manifest、CLI、MCP、Skill、文档、
README 示例、CHANGELOG 和公开数据安全；失败会阻止 release preparation。

涉及架构边界、数据权威来源、事务、安全或依赖变化时必须新增 ADR。自动检查只验证可
确定的同步关系，人工审查仍负责内容是否准确、必要且对用户有帮助。

## Consequences

- 功能工作在实现前需要功能文档或同等 issue 摘要。
- Release preparation 和 CI 增加确定性文档门禁。
- 公共命令、MCP 能力、配置或 Schema 变化不能只提交代码。
- 文档修正本身不会改变冻结 tag；`v0.2.0` 仍指向原提交。
- 门禁避免要求无意义文档：无影响时可明确记录“不涉及”及原因。
