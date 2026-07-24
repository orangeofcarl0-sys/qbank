# qbank Codex 与 MCP 接入

[English](../en/codex-integration.md) · [中文文档](README.md)

qbank 通过仓库规则、Skill、本地 CLI 和可选 STDIO MCP 与 Codex 协作。它不嵌入聊天界面、
不调用模型 SDK，也不要求 OpenAI API key。Codex 负责语义判断，qbank 负责确定性校验、事务
写入和产物生成。

## 三种独立状态

| 状态 | 作用 |
| --- | --- |
| 仓库级 Skill | 随题库保存的 `.agents/skills/`，提供通信协议和领域工具 |
| 用户级 Skill | `$HOME/.agents/skills/`，让其他项目发现已安装 Skill |
| Codex CLI | 可选外部命令；不可用不影响 Desktop/IDE 读取仓库级 Skill |

`codex check` 分别报告 `repository_ready`、`codex_cli_ready` 和 `degraded`。兼容字段 `ok`
只在仓库级必要检查失败时变为 `false`，因此 `ok: true` 不等同于外部 Codex CLI 可执行。

## 两个独立 Skill

| Skill | 职责 | 不负责 |
| --- | --- | --- |
| `$qbank` | 题库定位、上下文、权限、CLI 协议、校验和任务交接 | 具体电子化项目如何取舍字段或分类 |
| `$qbank-digitize` | PDF/扫描件访谈、字段策略、分类表、样本校准和批次验收 | 直接写 Markdown 或重实现事务 |

`$qbank-digitize` 是额外领域工具，不是通信协议的改造。它先形成
`digitization_decision_packet`；用户批准字段策略和代表样本后，再把明确执行范围交回
`$qbank`。

```powershell
qbank codex install-skill --skill qbank --user --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --dry-run --format json
```

PDF 电子化流程为：确认目标题库、来源和权限；检查实际 Schema、样式与分类表；批准字段策略
和样本；输出决策包；最后由 `$qbank` 执行 Schema 读取、dry-run、写入与验证。

## 跨项目上下文协议

用户级 Skill 不保存具体题库路径、任务状态或一次性授权。从其他项目处理资料时必须先确定：

- 任务目标与验收条件；
- 已验证的目标题库根目录；
- 明确来源文件或 URL；
- 工作流；
- `read_only`、`dry_run_only` 或 `write_authorized` 授权级别；
- 会影响结果的未解决问题。

qbank 命令始终以目标题库根目录为工作目录。来源项目默认只读。无法确认目标或写入范围时，
必须在 mutation 前停止，不得根据目录名或旧对话猜测。跨任务继续时重新验证根目录和
`integration_revision`。

## 检查、安装与更新

```powershell
qbank codex check --format json
qbank codex instructions --format markdown
qbank codex integration-status --format json
```

检查覆盖 `AGENTS.md`、Skill frontmatter、必要命令、项目/用户 Skill 漂移和一次短超时 Codex
CLI 探测。合法但修改或落后的 Skill 产生 warning，不自动覆盖。

默认安装范围等同 `--user`。目标不同且未指定 `--update` 时以退出码 5 拒绝覆盖。正式更新前
先检查逐文件 add/modify/delete 差异：

```powershell
qbank codex install-skill --skill qbank --project --update --dry-run --format json
qbank codex install-skill --skill qbank --project --update
qbank codex install-skill --skill qbank-digitize --user --update --dry-run --format json
qbank codex install-skill --skill qbank-digitize --user --update
```

正式更新使用同目录暂存和原子切换并保留备份。源、目标或内部文件含符号链接时拒绝安装。
自动化必须用 `--yes` 表示外层已明确授权。

## 数据操作边界

1. 创建交换数据前读取对应 Schema。
2. 题目、标签、视图、试卷和资产写入先 dry-run。
3. 正式写入后执行 `qbank validate --format json`。
4. 临时 AI 输出写入 `build/ai/`，生成试卷定义写入 `papers/generated/`，最终产物写入 `exports/`。
5. 保留来源；无法确认的信息保持 `draft`，不得编造答案或来源事实。
6. 未明确授权不得删除或覆盖。
7. 无人值守流程不得启动 `qbank preview --serve` 或 `qbank desktop`。

Studio 与 Codex 保持模块隔离：两者并列调用应用服务，桌面控制器不依赖 Codex 服务，Codex
服务也不依赖 Qt。

## 可选本地 MCP

```powershell
pip install "qbank[mcp]"
qbank codex install-mcp --project --dry-run --format json
qbank codex install-mcp --project --yes --format json
qbank codex mcp-check --format json
```

项目 MCP 配置写入当前题库 `.codex/config.toml` 的受管区块，并以绝对 `--repository` 参数绑定
题库。所有写操作分为 prepare 和 commit；prepare 返回差异、诊断、过期时间和
`repository_revision`，仓库变化后 commit 会拒绝。operation 状态持久化在
`.qbank/mcp-operations/`，重复 commit 只返回首次结果。

写工具覆盖题目导入与 patch、标签、paper、资产包、资产状态和 preferred representation；
不会启动 Ipe、浏览器或任意本地程序。MCP SDK、注册或 Codex CLI 缺失不影响 CLI、Studio
和 Skill，只会使 `integration-status` 报告 `DEGRADED`。

当前不提供 Studio 内嵌聊天、模型 API 封装、资源订阅或复杂 Prompt 模板。
