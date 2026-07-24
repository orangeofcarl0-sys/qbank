# 双语文档体系

> Status: implemented
>
> Target release: 0.3.0
>
> Tracking issue: repository documentation maintenance

## 用户目标

中文和英文读者都能从项目首页进入完整、连贯的 qbank 用户文档，并在任一页面明确切换语言，
而不需要猜测文件名或依赖浏览器翻译。

## 使用入口

- 根目录 `README.md`（简体中文）与 `README.en.md`（English）；
- `docs/README.md` 文档语言门户；
- `docs/zh-CN/` 与 `docs/en/` 中成对维护的用户文档。

原有 `docs/user-guide.md` 等稳定路径保留为兼容入口，并指向两种语言版本。

## CLI / Studio / MCP 对应关系

不改变 CLI、Studio 或 MCP 行为。三类入口的用户说明均纳入同一双语覆盖清单，命令名称、
字段名、诊断码和代码示例保持英文技术标识。

## 数据与配置变化

不改变题库数据、配置、Schema、索引或持久化格式。新增文档语言目录、语言门户和
`scripts/check_docs_sync.py` 中的确定性语言覆盖检查。

## 安全和失败行为

双语文件继续接受本机路径、私有身份和失效链接检查。受管文档缺少任一语言版本、语言切换
链接或必要命令时，docs-sync 失败并阻止发布。

## 兼容性与迁移

无需用户数据迁移。旧文档 URL 保留为语言选择页；现有中文 README 仍是默认项目首页。
`v0.2.0` tag、冻结制品、CLI、JSON、Markdown、Schema 和 MCP 契约均不变。

## 测试与验收

- 双语覆盖清单中的文件成对存在；
- 每个本地化页面具有返回文档门户和切换语言的链接；
- 两种语言的 CLI 参考覆盖全部公共命令；
- README 中的安全示例可执行；
- 所有本地 Markdown 链接有效，公开文本无本机路径或私有身份。

## 当前限制

首阶段本地化用户入口、操作指南、接口参考、Studio、Codex、兼容性和已知限制。ADR、内部
架构、代码审查和设计研究仍以其原始语言维护；它们在文档门户中明确标记为维护者参考资料。
