# 文档地图

本页说明文档的目标读者、权威范围和变更触发条件。

| 文档 | 主要读者 | 内容边界 | 需要更新的变化 |
| --- | --- | --- | --- |
| `README.md` | 首次访问者 | 定位、核心能力、快速开始、入口与限制 | 主要能力、安装或项目边界 |
| `CHANGELOG.md` | 用户与维护者 | 按版本记录用户可见变化 | 用户可见行为、依赖或兼容性 |
| `CONTRIBUTING.md` | 贡献者 | 提交流程、门禁与版本规则 | 开发或发布流程 |
| `SECURITY.md` | 安全研究者 | 支持版本、报告方式与安全边界 | 支持周期或报告渠道 |
| `docs/zh-CN/`、`docs/en/` | 中文/英文用户 | 成对维护的用户文档 | 任意用户可见行为 |
| `docs/*` 稳定入口页 | 已有外部链接 | 选择语言并转到本地化正文 | 本地化路径变化 |
| `docs/*/user-guide.md` | CLI 用户 | 完整日常工作流 | 数据与命令行为 |
| `docs/*/cli-reference.md` | 自动化用户 | 公共命令清单与分组 | 命令新增、重命名、删除 |
| `docs/*/desktop-editor.md` | Studio 用户 | 桌面操作与失败状态 | Studio 交互 |
| `docs/*/installation.md` | 安装与部署用户 | 制品校验、安装、升级与卸载 | 版本、制品或安装行为 |
| `docs/*/codex-integration.md` | Codex/MCP 用户 | Skill、MCP、授权和恢复 | manifest、Skill、MCP |
| `docs/features/capability-matrix.md` | 集成维护者 | CLI、Studio、MCP 能力映射 | capability manifest 或入口 |
| `docs/*/compatibility-policy.md` | 集成方 | 稳定接口、迁移和版本规则 | 公共契约 |
| `docs/*/compatibility-0.3.0-beta.1.md` | beta 用户 | 当前软件、Protocol 与 Schema 矩阵 | 0.3 beta 冻结 |
| `docs/*/known-limitations-0.2.0.md` | 部署者 | 0.2.x 版本限制 | 0.2.x 限制澄清 |
| `docs/*/known-limitations-0.3.0-beta.1.md` | beta 部署者 | unsigned beta 与运行边界 | beta 限制变化 |
| `docs/localization.md` | 文档维护者 | 语言范围、编写与同步门禁 | 支持语言或本地化范围 |
| `docs/architecture.md` | 维护者 | 分层、数据和事务边界 | 架构边界 |
| `docs/monorepo-development.md` | 开发者 | Studio/CLI/MCP/Legacy 目录、三级检查与统一构建 | 仓库结构、版本或构建入口 |
| `docs/ui/design-system.md` | Studio 维护者 | 当前 Tauri Studio 的视觉、状态、截图与 Legacy 边界 | Studio 视觉或交互 |
| `docs/ui/reference-evaluation.md` | Legacy 维护者 | 历史 Qt/PySide6 参考与依赖决策 | Legacy 严重兼容修复 |
| `docs/adr/` | 维护者 | 重要决定及其后果 | 架构、权威源、事务、安全、依赖 |
| `docs/features/` | 产品与实现人员 | 单项功能的完整契约 | 功能生命周期状态 |
| `.agents/skills/qbank/` | Codex | 确定性操作协议 | 工作流、命令、授权 |

## 导航原则

README 只承担项目首页职责。完整命令进入 CLI 参考，操作流程进入用户指南，内部设计进入
架构与 ADR，特定功能的跨界面契约进入 `docs/features/`。同一事实需要多处出现时，应链接
到权威文档，并由自动门禁验证必要的镜像内容。

用户文档使用 `docs/zh-CN/` 与 `docs/en/` 明确分离正文语言。旧顶层路径只承担兼容入口职责；
维护者资料可保留原始工作语言，但其中形成用户契约的内容必须同步进入双语用户文档。

## 发布材料

`build/public-release-prep/` 是本地、可重建的发布审查输出，不进入分发包。正式 Release
notes 从 CHANGELOG 与对应版本的兼容性文档生成；wheel、sdist 和 checksums 必须来自同一
发布提交。
