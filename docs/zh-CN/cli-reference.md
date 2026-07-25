# CLI 命令参考

[English](../en/cli-reference.md) · [中文文档](README.md)

本文列出 qbank `0.3.0-beta.1` 的公共命令入口。本 beta 保留 0.2.0 已记录的命令名称；
参数、默认值和退出码以各命令的 `--help`、[当前兼容矩阵](compatibility-0.3.0-beta.1.md)
及[0.2.0 兼容性基线](compatibility-0.2.0.md)为准。

## 项目、诊断与索引

| 命令 | 用途 |
| --- | --- |
| `qbank init` | 初始化题库；冲突时零写入 |
| `qbank status` | 汇总题库、验证和索引状态 |
| `qbank doctor` | 检查配置、工具链、Schema 和索引 |
| `qbank schema` | 输出 Question、Paper、Patch 或 Asset Schema |
| `qbank index rebuild` | 原子重建 SQLite 搜索投影 |
| `qbank preview` | 构建静态预览；`--serve` 仅供交互使用 |
| `qbank desktop` | 启动可选 Studio 桌面编辑器 |

## 题目与检索

| 命令 | 用途 |
| --- | --- |
| `qbank add` | 添加单题 |
| `qbank ingest` | 从 JSON/JSONL 批量导入 |
| `qbank patch` | 结构化修订题目 |
| `qbank delete` | 删除题目及对应权威历史 |
| `qbank validate` | 校验全部或指定题目 |
| `qbank list` | 列出题目 |
| `qbank query` | 使用结构化筛选查询 |
| `qbank search` | 使用只读 SQLite 索引全文检索 |
| `qbank get` | 读取完整题目 |
| `qbank export` | 导出题目集合 |

## 标签与保存视图

| 命令 | 用途 |
| --- | --- |
| `qbank tag list` | 列出标签 |
| `qbank tag show` | 查看标签及关联题目 |
| `qbank tag stats` | 输出标签统计 |
| `qbank tag cooccur` | 计算标签共现 |
| `qbank tag rename` | 重命名标签 |
| `qbank tag merge` | 合并标签 |
| `qbank tag normalize` | 规范化标签 |
| `qbank tag delete` | 删除标签引用 |
| `qbank view list` | 列出保存视图 |
| `qbank view apply` | 应用保存视图 |
| `qbank view save` | 保存查询快照 |
| `qbank view rename` | 重命名保存视图 |
| `qbank view delete` | 删除保存视图 |

## 资产

| 命令 | 用途 |
| --- | --- |
| `qbank asset list` | 列出题目资产 |
| `qbank asset show` | 查看逻辑资产与表示 |
| `qbank asset validate` | 校验资源边界和生命周期 |
| `qbank asset add` | 添加受管资源 |
| `qbank asset ingest` | 导入逻辑资产包 |
| `qbank asset replace` | 追加替代表示 |
| `qbank asset normalize` | 将旧路径转换为逻辑资产 |
| `qbank asset finalize` | 更新资产生命周期状态 |
| `qbank asset set-render` | 设置首选渲染表示 |
| `qbank asset set-editor` | 设置首选编辑表示 |
| `qbank asset render` | 从可编辑源重新渲染 |
| `qbank asset edit` | 启动已配置的交互式编辑器 |
| `qbank asset open` | 使用系统程序打开资源 |

`asset edit`、`asset open` 和 `preview --serve` 不得由无人值守自动化静默启动。

## 试卷

| 命令 | 用途 |
| --- | --- |
| `qbank paper validate` | 校验试卷定义和题目引用 |
| `qbank paper build` | 构建学生、答案或解析版本 |

## Codex 与 MCP

| 命令 | 用途 |
| --- | --- |
| `qbank codex check` | 检查仓库、Skill 和 Codex CLI 就绪状态 |
| `qbank codex instructions` | 输出集成规则和工作流 |
| `qbank codex integration-status` | 汇总 Skill 与 MCP 状态 |
| `qbank codex install-skill` | 预演或安装项目/用户 Skill |
| `qbank codex install-mcp` | 预演或注册本地项目 MCP |
| `qbank codex uninstall-mcp` | 预演或移除项目 MCP 注册 |
| `qbank codex mcp-check` | 检查 MCP 安装和配置 |
| `qbank mcp` | 启动本地 STDIO MCP Server |

所有可能写入配置或题库的命令都应先执行 `--dry-run`。机器消费输出时使用
`--format json`，并依据退出码与稳定诊断码判断结果。
