# ADR 0007：分离资料数字化、qbank 权威层与文档构建

- 状态：Accepted
- 日期：2026-07-26

## 上下文

真实资料电子化同时包含来源提取、AI 语义判断、题库权威写入和正式文档排版。若把这些职责
全部放入 qbank 核心，会让 OCR 引擎、来源格式、agent 行为和出版工具链与权威题库耦合，
扩大依赖、安全边界、事务范围和长期维护成本。

上一版需求曾把通用候选模型、审批包、持久化作业状态、交付配置和完整构建清单列为路线
目标。现阶段没有足够的跨项目证据证明这些平台化抽象值得进入 qbank，也不应为了单个
电子化项目建设重型作业平台。

## 决定

继续保留三层分离原则：

1. **资料数字化层**位于来源项目。MinerU 或其他外部工具只负责提取；AI 与
   `$qbank-digitize` 根据来源证据整理 Question JSONL、Asset packages 和
   `review.md`。
2. **qbank 权威层**只接受现有 Question/Asset 契约，并通过现有 MCP
   `prepare → inspect → commit → validate` 写入。Markdown 与逻辑资产在成功提交后
   才成为权威数据。
3. **文档构建层**位于交付项目。它通过现有 MCP 查询和读取题目，由 AI 与 Skill 生成
   `selection.yaml` 和 TeX，再使用固定模板与 `latexmk` / XeLaTeX 生成派生产物。

当前先实施轻量 AI 工作流。qbank：

- 不内置 MinerU 或其他 OCR 引擎；
- 不新增 Candidate Schema、Question/Asset/Paper Schema 字段或持久化作业数据；
- 不新增 MCP 工具；
- 不执行任意 TeX 或来源项目脚本；
- 不重构核心以承载数字化或出版平台。

`CandidateBlock`、`DigitizationDecisionPacket`、`DeliveryProfile`、完整
`BuildManifest`、作业状态平台和逐页出版验收降级为远期可选方案。它们只有在多个独立
项目形成稳定共性、轻量文件约定明显不足，并完成单独的安全与兼容性设计后，才可重新
提案；本 ADR 不承诺建设通用 OCR 平台或完整出版系统。

## 后果

### 正面

- qbank 核心继续专注权威题库、确定性校验和安全事务。
- MinerU、模型、分类规则和 TeX 工具链可以在项目侧独立替换。
- 中间产物可直接审阅、删除和重建，不需要部署新的数据库或服务。
- 现有 CLI、Studio、MCP、Schema 和题库无需迁移。

### 代价

- 来源整理与文档排版仍需要项目侧 Skill、模板和少量编排。
- 题目与资产的多个 MCP operation 目前不构成跨操作原子事务，调用方必须按依赖顺序
  提交、验证并报告部分成功。
- `selection.yaml`、TeX 模板和构建目录暂时是项目约定，不具备 qbank 公共兼容承诺。
- 高风险出版仍需要人工抽查；当前方案不提供通用逐页验收平台。

## 被拒绝的方案

### 把 MinerU 或 OCR adapter 放进 qbank

拒绝。它会把大型、变化快且可能涉及外部服务的依赖引入权威仓储。

### 建设持久化 Candidate/Job 平台

当前拒绝。文件级 `questions.jsonl`、Asset packages 和 `review.md` 已足以支持可审阅
交接；平台化没有被跨项目需求证明。

### 在 MCP 中增加 TeX 构建工具

拒绝。现有 MCP 有意绑定单一题库根并限制文件和进程能力；任意构建会显著扩大攻击面。

### 让 AI 或脚本直接写 Markdown

拒绝。它绕过现有 Schema、diff、revision、事务、历史和验证边界。

## 验证

- 仓库 Skill 与包内初始化资源逐字节一致。
- 文档同步门禁验证中英文需求编号、导航和语言纯度。
- 公开合成 fixture 覆盖 MinerU 结果到 JSONL/资产包，再到现有 MCP 提交与校验。
- 交付 smoke 只通过现有 MCP 读取并在隔离目录构建固定 TeX，不修改题库。
