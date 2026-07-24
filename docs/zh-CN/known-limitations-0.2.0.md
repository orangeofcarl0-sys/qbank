# qbank 0.2.0 已知限制

[English](../en/known-limitations-0.2.0.md) · [中文文档](README.md)

本文记录 0.2.0 冻结时已知但不构成 P0/P1 阻断的问题。这些是明确支持边界，不代表隐含能力。

## 文件系统与并发

- 主要支持本机常规文件系统上的单题库工作区。
- UNC、网络盘、NFS/SMB/CIFS、云同步目录等锁语义不确定的文件系统会由 `qbank doctor` 警告。
- 仓库锁只协调遵守 qbank 协议的 CLI、Studio 和 MCP，不阻止其他程序直接改写文件。
- 不承诺多机同时写同一网络共享题库的安全性。
- Windows containment 使用解析路径并拒绝 junction、符号链接和其他 reparse point 逃逸。

## 事务与外部修改

- 写入使用同目录临时文件、仓库锁和 `.qbank/transactions/` journal。下一次写入会恢复未完成
  的 prepared transaction，或清理已 committed journal。
- MCP 响应丢失后可从持久化 operation 返回首次结果。权威文件已改变但 operation 未记录完成
  的极窄崩溃窗口会保守拒绝重放，并要求检查 revision。
- revision 在关键边界重算，不使用可能漏检外部修改的长期缓存；但无法抵御有写权限的恶意
  程序在单个原子替换系统调用内部制造竞态。

## 性能

- 健康索引上的 `search` 和 MCP 结构化查询读取 SQLite 摘要；`question_get` 才加载完整题目。
- 为发现外部 Markdown 修改，搜索前按字节计算内容 revision，复杂度与题目 Markdown 总字节数
  相关，而非命中数。
- `index rebuild` 解析全部题目并重建 trigram FTS，是大型题库最昂贵的维护操作。
- 批量 prepare/commit 的主要成本是完整 Markdown 解析、Pydantic 校验和确定性 revision。
- 0.2.0 不使用常驻文件监视器或不安全的进程内缓存。

## 可选依赖与渲染

- Studio 需要 `qbank[desktop]`；核心 CLI 不包含 Qt。
- 本地 MCP STDIO 需要 `qbank[mcp]`；缺失不影响 CLI、Studio 或 Skill。
- DOCX 依赖外部 Pandoc；缺失时 Markdown、HTML 和 JSON 仍可用。
- 公式预览默认使用 MathJax CDN；完全离线时可能显示 TeX 源文本。
- 原始 HTML 禁用。远程图片允许但警告，且不会自动下载。
- Ipe 编辑和渲染依赖本机 Ipe；普通 PNG 不会显示虚假的 Ipe 编辑能力。

## Codex 集成与产品边界

- 仓库 Skill、用户 Skill 和 Codex CLI 是独立状态；`ok: true` 不代表 Codex CLI 可执行。
- qbank 不提供模型 SDK、API key 管理、Studio 内嵌聊天、MCP HTTP transport、Prompts 或订阅。
- qbank 不包含 OCR、扫描版自动分题、答案推断、在线考试或自动组卷算法。
- `$qbank-digitize` 帮助定义电子化规则与校准样本，但事实、分类和最终授权由用户负责。
- 第三方 Python API 尚未冻结；稳定边界是[兼容性基线](compatibility-0.2.0.md)记录的 CLI、
  Schema、Markdown、JSON、Skill 与 MCP。
