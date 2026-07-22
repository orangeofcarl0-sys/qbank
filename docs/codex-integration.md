# qbank Codex 接入指南

qbank 通过仓库规则、Skill 和本地 CLI 与 Codex 协作。该接入不嵌入聊天界面、不调用模型
SDK，也不要求 OpenAI API key。Codex 负责理解请求和作出语义选择，qbank 负责确定性校验、
事务写入和产物生成。

## 三种独立状态

| 状态 | 作用 |
| --- | --- |
| 仓库级 Skill | 随题库保存的 `.agents/skills/qbank/`，定义该项目内的工作流 |
| 用户级 Skill | `$HOME/.agents/skills/qbank/`，让其他项目发现相同工作流 |
| Codex CLI | 可选外部命令；不可用时不影响 Desktop 或 IDE 读取仓库级 Skill |

`codex check` 分别报告 `repository_ready`、`codex_cli_ready` 和 `degraded`。兼容字段 `ok` 只在
仓库级必要检查失败时变为 `false`，因此 `ok: true` 不等同于外部 Codex CLI 可执行。

## 检查与工作流说明

```powershell
qbank codex check --format json
qbank codex instructions --format markdown
qbank codex instructions --format json
```

检查内容包括 `AGENTS.md`、Skill frontmatter、必要命令、项目与用户 Skill 漂移、当前项目路径
和一次短超时 Codex CLI 版本探测。合法但经过用户修改或落后的 Skill 产生 warning，不会自动
覆盖。

`codex instructions` 输出结构化工作流、前置条件、写入性质、dry-run 要求、成功条件和恢复
动作。旧 `command_sequences` 字段继续保留以兼容现有调用方。

## 安装用户级 Skill

默认目标与 `--user` 相同，均为 `$HOME/.agents/skills/qbank/`。用户级安装以当前项目 Skill
为来源，因此可以把已审查的仓库规则带到其他题库。

```powershell
qbank codex install-skill --user --dry-run --format json
qbank codex install-skill --user
```

自动化环境必须显式授权：

```powershell
qbank codex install-skill --user --yes --format json
```

目标已存在且内容不同时，未指定 `--update` 的命令以冲突退出码 5 拒绝覆盖。

## 更新 Skill

项目范围以安装包内的权威资源为来源，用户范围以当前项目 Skill 为来源。更新前先检查逐文件
add、modify 和 delete 差异：

```powershell
qbank codex install-skill --project --update --dry-run --format json
qbank codex install-skill --project --update
qbank codex install-skill --user --update --dry-run --format json
qbank codex install-skill --user --update
```

正式更新采用同目录暂存和原子切换。项目备份保存到配置 state 目录的
`codex-skill-backups/`，用户备份保存到
`$HOME/.agents/.qbank-backups/skills/qbank/`。源、目标或内部文件包含符号链接时，安装会被
拒绝。

## 数据操作边界

Codex 使用 qbank 时应遵守以下规则：

1. 创建交换数据前读取对应 Schema。
2. 题目、标签、视图和资产写入均先执行 dry-run。
3. 正式写入后执行 `qbank validate --format json`。
4. 临时 AI 输出保存到 `build/ai/`。
5. 生成的试卷定义保存到 `papers/generated/`，最终产物保存到 `exports/`。
6. 保留来源位置，将无法确认的信息保持为 `draft`，不得推断答案或来源事实。
7. 未经明确授权不得执行删除、覆盖或其他破坏性操作。
8. 无人值守流程不得启动 `qbank preview --serve` 或 `qbank desktop`。

仓库级 `$qbank` Skill 是详细命令工作流的权威来源。Studio 与 Codex 保持模块隔离：两者都是
应用服务的展示适配器，桌面控制器不依赖 Codex 服务，Codex 服务也不依赖 Qt。

## 当前边界

qbank 0.1.0 不提供 MCP Server、Studio 内嵌聊天或模型 API 封装。未来的自动化适配器应直接
调用类型化应用服务，不应解析 CLI 输出或绕过 Markdown、历史、校验和索引事务。
