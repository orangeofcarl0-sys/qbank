# qbank 路线图

[English](../en/roadmap.md) · [中文文档首页](README.md)

本路线图描述 `0.3.x` 之后的优先方向，不承诺发布日期。实施前仍需建立独立 feature 文档
或 issue 摘要，并按[功能生命周期](../feature-lifecycle.md)完成双语文档、测试、兼容性和
限制说明。

![qbank 路线图：以统一题库核心为基础，优先验证多 agent 互操作、轻量资料入库和轻量 TeX 交付流程](../assets/readme/roadmap.svg)

## 当前基础

qbank 已具备继续扩展所需的稳定边界：

- Markdown 题目、逻辑资产和项目定义是权威文件；
- Studio、CLI、Skill 和可选 MCP 共用一个应用核心；
- 写入采用 dry-run、revision、仓库锁、事务、历史与失败恢复；
- MCP 已支持查询、取题、Schema、prepare、commit 和 validate；
- `$qbank-digitize` 已提供字段策略、分类映射、代表样本与只读交换检查；
- `$qbank-deliver` 已提供只读快照、受限 TeX、原创中文模板与原子 PDF 构建；
- 公开示例和测试不包含真实试题或用户数据。

当前版本不包含 OCR 引擎，也不把 OCR 文本直接写入权威题目。

## 方向 A：更多 agent 与 host 的支持测试

目标是验证不同 host 正确理解同一 qbank 契约，而不是把某个 agent 产品写进核心：

- 提供经过验证的通用 STDIO MCP 配置与故障排查样例；
- 覆盖工具发现、Schema 读取、资源读取和两阶段写入；
- 验证授权缺失、operation 过期、revision 冲突、响应丢失和 server 重启；
- 使用跨项目 handoff fixture 保留目标题库、来源和写入授权；
- 记录真实验证过的 host、版本、操作系统与限制。

## 方向 B：轻量资料 → qbank

首个轻量垂直切片已经实现，并优先采用项目侧已有 MinerU 输出：

1. MinerU 在来源项目完成提取；
2. AI 与 `$qbank-digitize` 识别题目边界、公式、答案、分类和图片归属；
3. 生成 `questions.jsonl`、现有 Schema 的 Asset packages 和只含不确定项的
   `review.md`；
4. 使用现有 MCP `prepare → inspect → commit → validate` 写入 qbank；
5. 不确定内容保持 `draft`，来源文件、页码或范围及原题号保持可追溯。

不在 qbank 内置 MinerU，不建设通用 Candidate 数据库、作业状态平台或新的 MCP 工具。

## 方向 C：轻量 qbank → 正式交付物

首个轻量垂直切片已经由 `$qbank-deliver` 实现，交付流程仍留在项目侧：

1. 通过现有 MCP 查询和读取题目；
2. AI 与 `$qbank-deliver` 生成明确的 `selection.yaml` 和受限 TeX；
3. 固定模板负责页面、字体、编号、答案空间和内容版本；
4. `latexmk` / XeLaTeX 在隔离目录生成 PDF 或其他交付物；
5. 构建只读 qbank，并检查公式、图片、可读性和答案泄露。

`selection.yaml` 与 TeX 暂时是项目约定，不成为新的 Paper Schema。完整需求见
[资料 → qbank → 正式交付物](source-qbank-deliverables.md)。

## 远期可选研究

`CandidateBlock`、`DigitizationDecisionPacket`、`DeliveryProfile`、完整
`BuildManifest`、持久化作业平台和自动逐页出版验收不属于当前目标。只有多个独立项目
证明轻量文件约定不足时，才为具体问题重新提案；qbank 不承诺建设通用 OCR 平台或完整
出版系统。

## 贯穿方向：MCP 可理解性与可观测性

- 维护独立的[MCP 使用指南](mcp-guide.md)；
- 从 capability manifest 校验工具、资源和访问级别说明；
- 让 operation revision、expiry、warning 和恢复动作在 host 中可见；
- 使用公开合成题库运行客户端契约与重启恢复 smoke；
- 保持 MCP 为可选本地适配器，不让 CLI、Studio 或数据格式依赖特定 agent；
- 数字化和 TeX 构建复用现有工具，不增加任意文件或进程执行能力。

## 共同完成标准

一项路线图能力只有在具备明确用户目标、边界、失败行为、双语文档、公开合成 fixture、
确定性契约和恢复测试后才可标记为 implemented。来源内容与 AI 推断必须可区分，不确定
内容不得静默提升为已确认事实，且不得为了单个项目扩展 qbank 核心。
