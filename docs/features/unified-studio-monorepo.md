# 统一 QBank Studio 单仓库结构

> Status: implemented
>
> Target release: 0.3.0
>
> Tracking issue: 本地结构归并任务

## 用户目标

让命令行、MCP、Codex Skill、现代 QBank Studio 与 Qt Legacy 客户端共享同一套 qbank
数据模型和应用服务，同时允许现代 Studio 独立打包、安装和启动。

## 使用入口

- 桌面用户通过 QBank Studio 安装器或便携包启动现代 Tauri 客户端。
- 自动化用户继续使用 `qbank` CLI。
- Codex 用户继续使用仓库 Skill 或可选 MCP。
- `qbank desktop` 保留为 QBank Studio Legacy 回退入口。

## CLI / Studio / MCP 对应关系

四个入口属于同一产品。CLI、MCP、Tauri sidecar 与 Qt Legacy 都调用
`qbank.application` 及同一 composition root，不复制题目解析、Schema、项目锁、事务、
历史、索引或资产生命周期规则。Studio Protocol v1 只负责 Tauri 前端与本地 sidecar
之间的展示层通信。

## 数据与配置变化

题库 Markdown、资产 manifest、项目配置、历史和 SQLite 投影格式均不改变。
Question、Asset、Paper Schema 继续使用独立版本 `1.0`。本次只调整源码、构建入口和
发布制品的仓库位置，不执行题库迁移。

## 安全和失败行为

sidecar 仍只接受固定 JSON-RPC 方法，stdout 只输出协议消息。所有写入继续由 qbank
应用服务持有项目锁并执行 dry-run、事务、历史和索引同步。Tauri 权限仍只允许启动
固定 sidecar，不开放任意命令或文件系统访问。

## 兼容性与迁移

`v0.2.0` tag 永久不变。统一开发线从 Python 版本 `0.3.0b1` 开始，对外显示为
`0.3.0-beta.1`。现有题库无需迁移；Qt 客户端仅更名为 QBank Studio Legacy，并保留
原 `qbank desktop` 入口。

## 测试与验收

结构归并只要求验证 Python 导入和架构契约、Studio Protocol、Tauri 开发构建、
sidecar 启动、一个打开—编辑—保存—公式预览—图片操作 smoke，以及同一提交生成
wheel、安装器和便携包。未改变行为的发布级 UAT 与万题基准不重复执行。

## 当前限制

现代 Studio 仍是 Windows Tauri 应用；代码签名、完整安装矩阵和真实大规模 UAT 只在
release 级门禁执行。Qt Legacy 仅接受数据损坏、安全或严重兼容性修复。
