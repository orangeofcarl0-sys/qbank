# qbank Codex 接入指南

qbank 通过仓库规则、Skill 和本地 CLI 与 Codex 协作。该接入不嵌入聊天界面、不调用模型
SDK，也不要求 OpenAI API key。Codex 负责理解请求和作出语义选择，qbank 负责确定性校验、
事务写入和产物生成。

## 三种独立状态

| 状态 | 作用 |
| --- | --- |
| 仓库级 Skill | 随题库保存的 `.agents/skills/`，提供通信协议和可选领域工具 |
| 用户级 Skill | `$HOME/.agents/skills/`，让其他项目分别发现已安装的 Skill |
| Codex CLI | 可选外部命令；不可用时不影响 Desktop 或 IDE 读取仓库级 Skill |

`codex check` 分别报告 `repository_ready`、`codex_cli_ready` 和 `degraded`。兼容字段 `ok` 只在
仓库级必要检查失败时变为 `false`，因此 `ok: true` 不等同于外部 Codex CLI 可执行。

## 两个独立 Skill

| Skill | 职责 | 不负责 |
| --- | --- | --- |
| `$qbank` | 题库定位、上下文、权限、CLI 协议、写入校验和任务交接 | 具体电子化项目如何取舍字段或制定分类规则 |
| `$qbank-digitize` | PDF/扫描件项目访谈、字段策略、分类表、样本校准和批次验收 | 直接写题目 Markdown、替代 qbank Schema 或重新实现写入事务 |

`$qbank-digitize` 是额外领域工具，不是 `$qbank` 通信协议的一部分。它先形成
`digitization_decision_packet`；只有在用户批准字段策略和代表性样本后，才把明确的执行范围
交回 `$qbank`。新初始化题库同时包含两个 Skill，但可分别安装或更新：

```powershell
qbank codex install-skill --skill qbank --user --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --dry-run --format json
```

省略 `--skill` 时继续选择 `qbank`，保持旧行为兼容。

### PDF 电子化使用顺序

1. `$qbank` 确认目标题库、来源位置和授权边界；来源项目默认只读。
2. `$qbank-digitize` 检查来源样式、分类表和实际 Schema，只询问无法从材料中确认的关键取舍。
3. 用户批准字段策略、分类映射和覆盖主要版式的代表性样本。
4. `$qbank-digitize` 输出 `digitization_decision_packet`，其中记录来源范围、配置路径、样本、
   未解决队列、批次限制、验收条件和有效授权。
5. `$qbank` 重新接管任务，按既有协议执行 Schema 读取、dry-run、正式写入和验证。

若字段策略或来源版式发生变化，应回到 `$qbank-digitize` 重新校准受影响样本；普通的查询、
修订、组卷和导出仍直接使用 `$qbank`，无需经过电子化工具。

## 跨项目上下文协议

用户级 Skill 只承载可复用的 qbank 操作方法，不保存具体题库路径、当前任务状态或一次性的
授权信息。当 Codex 从其他项目处理资料时，必须先建立以下上下文：

- 任务目标与可观察的验收条件；
- 已验证的目标题库根目录；
- 明确的来源文件或 URL；
- 所选工作流；
- `read_only`、`dry_run_only` 或 `write_authorized` 授权级别；
- 尚未解决且会影响结果的问题。

qbank 命令始终以目标题库根目录作为工作目录执行。来源项目默认只读，除非用户对该项目
另行明确授权。若无法确认目标题库或写入范围，Codex 应在执行 mutation 前停止并询问，不能
根据仓库名称、相邻目录或旧对话自行推断。

`qbank codex instructions --format json` 的 `context_protocol` 提供当前项目根目录、必需字段、
授权级别、启动命令和完成交接字段。跨任务继续工作时，接收方应重新验证项目根目录及
`integration_revision`，而不是仅依赖聊天摘要。

## 检查与工作流说明

```powershell
qbank codex check --format json
qbank codex instructions --format markdown
qbank codex instructions --format json
```

检查内容包括 `AGENTS.md`、Skill frontmatter、必要命令、项目与用户 Skill 漂移、当前项目路径
和一次短超时 Codex CLI 版本探测。合法但经过用户修改或落后的 Skill 产生 warning，不会自动
覆盖。

`codex instructions` 输出上下文协议、结构化工作流、前置条件、写入性质、dry-run 要求、
成功条件和恢复动作。旧 `command_sequences` 字段继续保留以兼容现有调用方。

## 安装用户级 Skill

默认目标与 `--user` 相同。`--skill qbank` 安装到 `$HOME/.agents/skills/qbank/`，
`--skill qbank-digitize` 安装到 `$HOME/.agents/skills/qbank-digitize/`。用户级安装以当前项目
中所选 Skill 为来源，因此两个工具可以独立安装、更新或保留定制版本。

```powershell
qbank codex install-skill --skill qbank --user --dry-run --format json
qbank codex install-skill --skill qbank --user
qbank codex install-skill --skill qbank-digitize --user --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user
```

自动化环境必须显式授权：

```powershell
qbank codex install-skill --skill qbank-digitize --user --yes --format json
```

目标已存在且内容不同时，未指定 `--update` 的命令以冲突退出码 5 拒绝覆盖。

## 更新 Skill

项目范围以安装包内的所选权威 Skill 为来源，用户范围以当前项目中的同名 Skill 为来源。
更新前先检查逐文件 add、modify 和 delete 差异：

```powershell
qbank codex install-skill --skill qbank --project --update --dry-run --format json
qbank codex install-skill --skill qbank --project --update
qbank codex install-skill --skill qbank-digitize --user --update --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --update
```

正式更新采用同目录暂存和原子切换。`$qbank` 的项目备份继续保存到配置 state 目录的
`codex-skill-backups/`；其他 Skill 使用其下的同名子目录。用户备份保存到
`$HOME/.agents/.qbank-backups/skills/<skill-name>/`。源、目标或内部文件包含符号链接时，
安装会被拒绝。

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

仓库级 `$qbank` Skill 是详细命令工作流的权威来源；`$qbank-digitize` 只负责电子化决策和
校准，不直接访问写入事务。Studio 与 Codex 保持模块隔离：两者都是应用服务的展示适配器，
桌面控制器不依赖 Codex 服务，Codex 服务也不依赖 Qt。

## 可选本地 MCP

qbank 0.2.0 提供可选的本地 STDIO MCP Server。它与 CLI、Studio 并列调用同一组类型化应用
服务，不解析 CLI 输出，也不让 Studio 依赖 Codex。安装与项目注册均为显式操作：

```powershell
pip install "qbank[mcp]"
qbank codex install-mcp --project --dry-run --format json
qbank codex install-mcp --project --yes --format json
qbank codex mcp-check --format json
```

项目配置只写入当前题库的 `.codex/config.toml` 受管区块，并以绝对 `--repository` 参数绑定该
题库。所有写操作强制分为 prepare 与 commit 两阶段；prepare 返回字段差异、诊断、过期时间和
`repository_revision`，仓库变化后 commit 会拒绝执行。operation 状态保存在
`.qbank/mcp-operations/`，支持 `prepared`、`committing`、`committed`、`cancelled` 与
`expired`；重复 commit 返回首次结果，不重复写入。

首批写工具覆盖题目导入与 patch、标签变更、paper 保存、资产包导入、资产状态和 preferred
representation。资产工具不会启动 Ipe、浏览器或其他本地程序。`operation_get` 可在 STDIO
服务重启后读取持久化状态，`paper_history_get` 返回 paper 专用历史。

Codex 会根据 MCP tool annotations 对 `operation_commit` 等写工具请求确认。交互使用应保留
确认；已由外层自动化明确授权的隔离任务，可用 Codex 官方的逐工具设置精确批准 commit，而
不关闭其他工具的保护：

```powershell
codex exec `
  -c 'mcp_servers.qbank.tools.operation_commit.approval_mode="approve"' `
  "执行已经审阅的 qbank operation"
```

该设置属于 Codex 调用方策略，qbank 不会写入或默认启用它。
未安装 SDK、未注册 MCP 或 Codex CLI 不可用时，CLI、Studio 与 Skill 仍可独立工作，并由
`integration-status` 报告 `DEGRADED`。

当前仍不提供 Studio 内嵌聊天、模型 API 封装、资源订阅或复杂 Prompt 模板。
