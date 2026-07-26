# qbank 0.3.0-beta.2 兼容矩阵

[English](../en/compatibility-0.3.0-beta.2.md) · [中文文档](README.md)

| 契约或入口 | 冻结值 | 兼容性结论 |
| --- | --- | --- |
| 产品版本 | `0.3.0-beta.2` | 预发布，允许在后续 beta 修正非稳定界面 |
| Python 包 | `0.3.0b2`，Python 3.11 | CLI、MCP、sidecar 与 Legacy 共用 |
| Studio Protocol | `1.0` | Tauri Studio 与 sidecar 保持 v1 行为 |
| Question / Asset / Paper Schema | `1.0` | 与软件版本独立，无数据迁移 |
| 权威数据 | Markdown | SQLite、预览和导出均可重建 |
| 默认桌面入口 | Tauri QBank Studio | Windows x64；安装器与便携包 |
| 回退桌面入口 | `qbank desktop` | QBank Studio Legacy，仅维护严重问题 |
| Codex | CLI、仓库 Skill、可选 MCP | 共用 qbank application services |

`v0.2.0` 继续作为可获取的上一版本保留。0.3 beta 不改变该 tag 或既有制品，也不自动修改题库。

本开发线对 Studio Protocol `1.0` 采用兼容扩展：`repository.open` 与 `asset.list` 仅新增
字段，旧字段保持；`repository.rebuildIndex` 通过 `initialize.capabilities` 广告。题库
Markdown、SQLite 格式和公共 Schema 不变，不需要迁移。
