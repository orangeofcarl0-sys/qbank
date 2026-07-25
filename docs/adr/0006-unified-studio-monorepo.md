# ADR 0006：QBank Studio 归并到 qbank 单仓库

- 状态：已接受
- 日期：2026-07-26
- 目标版本：0.3.0

## 背景

现代 Tauri Studio 曾在相邻目录中开发，导致版本、构建、Protocol、sidecar 和文档
出现独立发布路线。实际上 Studio 是 qbank 的 presentation adapter，其权威写入依赖
qbank application services，不应成为第二个产品或第二套领域实现。

## 决策

采用轻量单仓库结构：

- Python 领域、应用与基础设施继续位于 `src/qbank/`；
- Tauri 前端和 Rust 壳位于 `apps/studio/`；
- Studio sidecar 位于 `src/qbank/studio_sidecar/`；
- Studio Protocol v1 位于根目录 `protocol/`；
- Qt 客户端迁入 `src/qbank/legacy_qt/`，作为维护回退；
- 根目录 Python 脚本统一编排 fast、integration、release 检查及 wheel、Studio、all 构建。

不引入 Nx、Turborepo、服务容器或插件系统。Tauri 可以独立安装，但其版本和制品必须
绑定到与 Python wheel 相同的 Git 提交。

## 被否决的方案

1. 保持两个仓库：会继续造成版本、文档和应用服务边界漂移。
2. 把领域逻辑移入 TypeScript 或 sidecar：会复制 Schema、事务和索引规则。
3. 引入重量级 monorepo 框架：项目规模不需要额外任务图和缓存服务。

## 后果

Studio 构建需要从 `apps/studio/` 运行 Node/Tauri 工具，但 sidecar 直接导入工作区中的
`qbank.studio_sidecar` 与 qbank application services。普通修改默认运行受影响的 fast
门；只有相关边界变化才运行 integration；release 门只用于冻结或发布。题库格式和
Schema 不发生迁移。
