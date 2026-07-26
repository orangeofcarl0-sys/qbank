# 资料 → qbank → 正式交付物：轻量工作流

> Status: implemented（轻量双向垂直切片）
>
> Target release: Unreleased；以 Skill 和项目内文件约定提供
>
> Implementation evidence: 公开合成 fixture、MCP 两阶段集成测试和真实 XeLaTeX smoke

## 用户目标

用户希望利用现成的 MinerU 结果和 coding agent，把 PDF、扫描件、图片或文档整理为
qbank 现有 Question JSONL 与 Asset package，再通过现有 MCP 两阶段写入进入权威题库。
反向工作流从 qbank 查询并取得题目，由 AI 和 Skill 生成 `selection.yaml` 与 TeX，使用
固定模板和标准 TeX 工具链生成 PDF 或其他正式交付物。

当前方案追求可理解、可复核和可替换，不建设通用 OCR 平台、持久化候选数据库、作业状态
平台或完整出版系统。

完整用户需求见：

- [中文：资料 → qbank → 正式交付物](../zh-CN/source-qbank-deliverables.md)
- [English: Source → qbank → formal deliverables](../en/source-qbank-deliverables.md)

## 使用入口

- `$qbank-digitize`：检查 MinerU 输出，确定字段与分类策略，生成 `questions.jsonl`、
  Asset packages 和只含不确定项的 `review.md`。
- `$qbank`：定位题库、读取实时 Schema，并在需要时提供 CLI 兼容路径。
- qbank MCP：使用现有 `schema_get`、`ingest_prepare`、`asset_ingest_prepare`、
  `operation_commit` 与 `question_validate` 完成权威写入。
- `$qbank-deliver`：使用现有 MCP 读取工具冻结 `selection.yaml`、Question JSONL
  快照和 Asset manifest，并通过原创固定模板构建 TeX/PDF；构建过程不修改 qbank。

## CLI / Studio / MCP 对应关系

| 阶段 | 当前入口 | 本需求是否新增公共接口 |
| --- | --- | --- |
| MinerU 提取 | 外部工具或来源项目脚本 | 否 |
| AI 整理 | `$qbank-digitize` | 仅更新 Skill 指引 |
| Schema 读取 | CLI `schema` / MCP `schema_get` | 否 |
| 题目准备与提交 | MCP `ingest_prepare` / `operation_commit` | 否 |
| 资产准备与提交 | MCP `asset_ingest_prepare` / `operation_commit` | 否 |
| 校验 | MCP `question_validate` | 否 |
| 查询与取题 | MCP `question_search` / `question_get` | 否 |
| TeX 与 PDF | `$qbank-deliver`、原创固定模板、`latexmk` / XeLaTeX | 仅扩展 Skill 安装选项 |
| Studio | 审阅已入库题目和资产 | 否 |

## 数据与配置变化

不修改 Question、Asset、Paper Schema，不新增 qbank 配置、数据库或持久化格式。轻量工作区
只是来源项目中的可删除中间产物：

```text
build/digitize/<job-name>/
├─ mineru/
├─ questions.jsonl
├─ assets/packages/
└─ review.md
```

交付项目可使用同样简单的派生目录：

```text
build/deliver/<job-name>/
├─ selection.yaml
├─ snapshot/
├─ content.tex
└─ output/<variant>/
```

`questions.jsonl` 必须符合运行中的 Question Schema；`assets/` 中的每个包必须符合运行中的
Asset Schema。`selection.yaml` 与 TeX 是项目侧约定，不成为新的 qbank 公共 Schema。

## 安全和失败行为

- MinerU、AI 和来源脚本不得直接修改 `questions/`、资产 manifest、历史或 SQLite。
- 所有正式写入遵循 `prepare → inspect → commit → validate`；仓库 revision 改变后必须
  重新 prepare。
- 题目和资产当前不是一个跨操作原子事务。存在依赖时先提交并验证资产，再提交题目；任何
  部分成功都必须明确报告，不得伪装为整体成功。
- 原资料保持只读，来源文件、页码或页码范围、原题号与必要复核备注必须能够追溯。
- 不确定的题目边界、公式、图片、答案或分类保留为 `draft` 并进入 `review.md`；不得补造。
- TeX 使用固定、受信任模板，参数以文件或参数数组传递；不得把来源文本拼成 shell 命令。
- 构建器禁用 shell escape，只接受明确的 qbank/常用数学命令白名单，拒绝 TeX
  注释、字符编码、内部或未知命令，并拒绝输出目录中的符号链接与 Windows reparse point。
- 文档构建只读 qbank，不修改题目、资产、Paper、历史或索引。

## 兼容性与迁移

- qbank 软件版本与 Question、Asset、Paper Schema 版本继续独立。
- 现有题库、Markdown、Paper、CLI、Studio、MCP 和 JSON 字段均不迁移。
- MinerU 输出结构变化由 Skill 或项目侧适配，不进入 qbank 核心。
- `selection.yaml` 和 TeX 模板继续作为 Skill 侧项目约定；只有出现多个已验证项目的稳定共性时，才
  另行评估公共契约。

## 测试与验收

- 用公开合成的 MinerU fixture 生成合法 `questions.jsonl`、Asset package 和最小
  `review.md`。
- 通过 `examples/workflows/lightweight/run_demo.py` 在新目录初始化隔离题库，真实完成
  MCP prepare/commit/validate、查询、快照与交付构建，不依赖现有题库。
- 使用只读检查器验证固定 review 表格、嵌入资产、来源页与逻辑资产双向关系。
- 验证不确定内容保持 `draft`，且每个来源至少包含文件、页码或范围及原题号（若存在）。
- 对资产和题目分别运行现有 MCP prepare、检查 diff、commit 和 validate。
- 在 revision 冲突、非法 JSONL、非法资产、缺图和校验失败时验证零静默覆盖及明确恢复动作。
- 通过 `question_search` / `question_get` 生成固定 `selection.yaml` 和 TeX。
- 用固定模板在隔离目录运行 `latexmk` / XeLaTeX，分别编译学生版、答案版和解析版，并
  检查 PDF 可打开、文本和公式可读、图片存在且各版本的答案/解析显隐正确。
- 验证 `--validate-only` 对交付工作区零写入，且三个版本分别原子替换并可同时保留。
- 运行文档同步门禁，确认中英文需求编号一致，Skill 仓库版与包内初始化资源逐字节一致。

## 当前限制

- qbank 不内置 MinerU，也不负责安装、运行或升级 MinerU。
- 当前没有通用候选数据库、作业调度、跨操作题目/资产事务或来源区域审阅器。
- 当前 MCP 不负责 TeX 构建，也不新增任意文件执行或输出工具。
- `CandidateBlock`、`DigitizationDecisionPacket`、`DeliveryProfile`、完整
  `BuildManifest`、作业状态平台与逐页出版验收仅是远期可选研究项，不属于当前目标或承诺。
- 正式排版效果依赖项目模板、字体和 TeX 环境；跨平台不承诺逐字节相同。

架构边界由
[ADR 0007](../adr/0007-separate-digitization-and-document-publishing.md)
确定。
