# qbank 0.2.0 已知限制

本文记录 0.2.0 冻结时已知但不构成 P0/P1 阻断的问题。它们是明确的支持边界，不应被理解为隐含能力。

## 文件系统与并发

- 0.2.0 主要支持本机常规文件系统上的单题库工作区。
- UNC 路径、映射网络盘、NFS/SMB/CIFS、云盘同步目录及其他锁语义不确定的文件系统会由 `qbank doctor` 给出 warning。
- 仓库锁只协调遵守 qbank 协议的 CLI、Studio 和 MCP 进程；不承诺阻止外部编辑器、同步软件或其他程序直接改写文件。
- 不承诺多台计算机同时写入同一个网络共享题库的安全性。
- Windows 上的文件名大小写遵循底层文件系统；containment 使用解析后的路径并拒绝 junction、符号链接及其他 reparse point 逃逸。
- 无 Windows 符号链接权限的环境会跳过两项 symlink 专用测试；测试套件仍会创建真实 junction，并验证 `..`、绝对路径、UNC、大小写、reparse point 和路径替换攻击。

## 事务与外部修改

- qbank 写入使用同目录临时文件、仓库锁和 `.qbank/transactions/` journal。启动下一次写入时会恢复未完成的 prepared transaction，或清理已标记 committed 的 journal。
- MCP commit 在响应丢失后可根据持久化 operation 返回首次结果。若进程在权威文件已改变但 operation 尚未记录完成的极窄窗口退出，系统会保守拒绝自动重放并要求检查当前 revision，避免二次写入。
- revision 会在关键边界重新计算，因此不会使用可能漏检外部修改的长期缓存；无法承诺抵御具有写权限的恶意程序在单个原子替换系统调用内部制造竞态。

## 性能

- 健康索引上的 `search` 和结构化 MCP 查询读取 SQLite 摘要，不解析全部 Question；`question_get` 才读取完整题目。
- 为可靠发现外部 Markdown 修改，搜索前仍会按字节计算题目源文件的内容 revision。该步骤是 O(题目 Markdown 总字节数)，不是 O(命中数)。
- `index rebuild` 必须解析全部题目并重建 trigram FTS；10,000 题规模下它仍是最昂贵的维护操作。
- 批量 prepare/commit 仍需在权威边界检查一致性。对 10,000 题仓库，它们的主要瓶颈是完整 Markdown 解析、Pydantic 校验和确定性 revision，而非 SQLite 查询。
- 0.2.0 不引入常驻文件监视器或不安全的进程内缓存。性能基准以冻结产物中的 `performance-report.json` 为准。

## 可选依赖和渲染

- Studio 需要 `qbank[desktop]`；CLI 核心安装不包含 Qt。
- 本地 MCP STDIO 需要 `qbank[mcp]`；未安装时 `qbank mcp` 明确失败，但 CLI、Studio 和 Skill 不受影响。
- DOCX 构建依赖外部 Pandoc。Pandoc 缺失时 Markdown/HTML/JSON 能力仍可用。
- 预览中的公式默认使用 MathJax CDN；完全离线时浏览器可能只显示 TeX 源文本。
- 原始 HTML 继续禁用。HTTP/HTTPS 和协议相对图片允许但产生 warning，qbank 不自动下载远程资源。
- Ipe 编辑与渲染依赖用户本机安装的 Ipe；普通 PNG 等资源不会虚假显示 Ipe 编辑能力。

## Codex 集成

- 仓库级 Skill、用户级 Skill 和外部 Codex CLI 是三种独立状态。`codex check` 的 `ok: true` 不等同于 CLI 可执行。
- Windows Microsoft Store app alias 可能因执行别名权限而拒绝启动。qbank 会继续探测 `CODEX_CLI`、PATH、npm 全局入口及仓库候选，并选择首个可运行项；所有候选的版本或失败原因都会保留。
- qbank 不提供模型 SDK、API key 管理、Studio 内嵌聊天、MCP HTTP transport、Prompts 或订阅。
- 真实 Codex MCP 写入仍受 Codex 客户端的逐工具批准策略约束；qbank 不静默放宽该策略。

## 产品范围

- qbank 不包含 OCR、扫描版自动分题、自动答案推断、在线考试服务或自动组卷算法。
- `$qbank-digitize` 用于帮助建立真实 PDF/扫描件电子化规则与校准样本，但事实确认、分类取舍和最终授权仍由用户负责。
- 第三方 Python API 尚未冻结。稳定边界是本文及[兼容性基线](compatibility-0.2.0.md)记录的 CLI、Schema、Markdown、JSON、Skill 和 MCP 接口。
