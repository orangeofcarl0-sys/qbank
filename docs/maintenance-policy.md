# 文档维护策略

本文定义 qbank 功能、文档和发布材料的共同维护规则。文档是产品契约的一部分，不是
发布后的补充工作。

## 强制影响检查

新增、修改或删除任何功能时，必须逐项判断并按真实影响更新：

1. `README.md` 的项目定位、核心能力和快速入口；
2. `CHANGELOG.md` 的用户可见变化；
3. 用户功能文档；
4. [CLI 命令参考](cli-reference.md)；
5. [Studio 操作说明](desktop-editor.md)；
6. MCP tools、resources 和两阶段写入语义；
7. Codex Skill、`AGENTS.md` 与 capability manifest；
8. 配置、Schema、诊断码和兼容性文档；
9. 安装、升级和迁移说明；
10. 测试、公开合成示例和必要截图；
11. 已知限制。
12. 受管用户文档的简体中文与英文版本；覆盖范围见[本地化策略](localization.md)。

不受影响的项目不要求制造无意义文字；功能文档应明确写出“不涉及”及原因。若变化涉及
架构边界、数据权威来源、事务、安全或依赖，必须新增 ADR。

受管用户文档不得在同一正文中交替使用中文和英文。命令、字段、Schema、诊断码和产品专名
保留原技术标识；解释性正文分别写入 `docs/zh-CN/` 与 `docs/en/`。任一语言版本发生用户可见
变化时，对应语言版本必须在同一变更中更新。

## 权威来源

| 内容 | 权威来源 | 镜像或消费者 |
| --- | --- | --- |
| CLI 行为 | Typer 命令树与应用服务 | CLI 参考、README、Skill |
| MCP 能力 | MCP 注册表与 capability manifest | capability matrix、Codex 文档 |
| Codex 工作流 | `codex_manifest.py` 和包内 Skill 资源 | 仓库 Skill、初始化产物 |
| 数据格式 | Pydantic 模型生成的 JSON Schema | 根 `schemas/`、用户文档 |
| Studio 交互 | `apps/studio/` 生产组件、应用服务契约与 Studio 文档 | Tauri fixture 截图、设计系统 |
| 版本历史 | `CHANGELOG.md` | Release notes |

镜像必须由生成器产生或接受逐字节一致性测试；不得长期维护未校验的第二份规则。
现代 Studio 的公开截图只使用 Tauri 生产组件与公开合成 fixture；Qt 捕获只作为
QBank Studio Legacy 维护证据，不得替代当前 README 截图。

## 变更记录要求

用户可见行为、默认值、输出、错误、性能边界或依赖变化必须进入 `CHANGELOG.md`。
纯拼写修正和不改变行为的内部重排可不单列，但仍须通过文档同步门禁。Schema 或配置
变化必须在兼容性文档中说明是否需要迁移；“无需迁移”也是明确结论。

## 发布门禁

运行 `python scripts/check_docs_sync.py`。门禁验证公共命令、MCP、manifest、Skill、双语覆盖
和文档的一致性，并执行两种 README 的安全示例。失败会阻止发布。门禁不能判断文档是否真正有用，
审查者仍需确认内容准确、具体且没有用模板占位符冒充完成状态。

发布准备还必须运行完整质量门和 `$oss-readiness`。任何未处理的高风险发现、未经授权的
身份公开、缺失许可证、真实题目或私密数据均为发布阻断项。
