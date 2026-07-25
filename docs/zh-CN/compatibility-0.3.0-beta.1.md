# qbank 0.3.0-beta.1 兼容矩阵

[English](../en/compatibility-0.3.0-beta.1.md) · [中文文档](README.md)

| 契约或入口 | 冻结值 | 兼容性结论 |
| --- | --- | --- |
| 产品版本 | `0.3.0-beta.1` | 预发布，允许在后续 beta 修正非稳定界面 |
| Python 包 | `0.3.0b1`，Python 3.11 | CLI、MCP、sidecar 与 Legacy 共用 |
| Studio Protocol | `1.0` | Tauri Studio 与 sidecar 保持 v1 行为 |
| Question / Asset / Paper Schema | `1.0` | 与软件版本独立，无数据迁移 |
| 权威数据 | Markdown | SQLite、预览和导出均可重建 |
| 默认桌面入口 | Tauri QBank Studio | Windows x64；安装器与便携包 |
| 回退桌面入口 | `qbank desktop` | QBank Studio Legacy，仅维护严重问题 |
| Codex | CLI、仓库 Skill、可选 MCP | 共用 qbank application services |

`v0.2.0` 仍是不可变基线。0.3 beta 不移动旧 tag，不覆盖旧制品，也不自动修改题库。
