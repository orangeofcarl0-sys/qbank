# 资料 → qbank → 正式交付物

[English](../en/source-qbank-deliverables.md) · [中文文档首页](README.md)

本文定义一套轻量、可审阅的 AI 工作流。它优先复用 MinerU、coding agent、qbank
现有 Schema 与 MCP，以及成熟的 TeX 工具链；不把 qbank 扩展成 OCR 作业平台或完整
出版系统。

## 1. 目标与非目标

目标工作流分为两个相互独立、以 qbank 为边界的方向：

```mermaid
flowchart LR
    A["资料"] --> B["MinerU 提取"]
    B --> C["AI + qbank-digitize Skill 整理"]
    C --> D["questions.jsonl + Asset packages + review.md"]
    D --> E["qbank MCP<br/>prepare → inspect → commit → validate"]
    E --> F["qbank 权威题库"]
    F --> G["MCP 查询与取题"]
    G --> H["AI + qbank-deliver Skill<br/>selection.yaml + TeX"]
    H --> I["固定 TeX 模板"]
    I --> J["latexmk / XeLaTeX"]
    J --> K["PDF 或其他交付物"]
```

当前方案明确不以以下事项为目标：

- 在 qbank 内置、托管或封装 MinerU；
- 建设通用 OCR adapter 平台、Candidate 数据库或持久化作业状态系统；
- 修改 Question、Asset、Paper Schema；
- 增加 MCP 工具或扩大 MCP 的文件、进程权限；
- 重构 qbank 核心以承载来源处理或出版编排；
- 建设通用模板设计器、完整出版系统或逐页验收平台。

## 2. 边界与权威来源

| 内容 | 位置 | 权威性 |
| --- | --- | --- |
| 原始 PDF、图片、DOCX、答案册、分类表 | 来源项目 | 来源证据，只读 |
| MinerU 输出 | `build/digitize/<job>/mineru/` | 可重建中间产物 |
| `questions.jsonl`、Asset packages、`review.md` | 来源项目工作区 | 可审阅交换产物 |
| 题目 Markdown、逻辑资产、历史 | qbank 项目 | 成功提交后的权威数据 |
| SQLite | qbank 项目 | 可重建查询投影 |
| `selection.yaml`、TeX、PDF | 交付项目工作区 | 可重建派生产物 |

资料数字化层、qbank 权威层和文档构建层相互分离。来源工具不得直接写权威数据；文档构建
不得反向修改题库。详细决定见
[ADR 0007](../adr/0007-separate-digitization-and-document-publishing.md)。

## 3. 方向 A：资料 → qbank

### 3.1 最小工作区

```text
build/digitize/<job-name>/
├─ mineru/
├─ questions.jsonl
├─ assets/
│  └─ packages/
└─ review.md
```

- `mineru/`：复制或引用现有 MinerU 输出；qbank 不负责运行 MinerU。
- `questions.jsonl`：逐行 Question JSON，严格遵循目标题库的实时 Question Schema。
- `assets/`：现有 Asset Schema 接受的逻辑资产包；普通本地图片也必须遵守题库资产边界。
- `review.md`：只记录真正不确定的题目、公式、图片、答案和分类问题。已确认内容、流水账、
  全量题目摘要和重复日志不进入此文件。

项目可另外保留简单的字段策略或分类映射文件，但这些文件只是 Skill 工作材料，不是新的
qbank Schema，也不要求建立数据库。

在任何 MCP prepare 前运行只读检查：

```powershell
python .agents/skills/qbank-digitize/scripts/check_exchange.py build/digitize/<job-name>
```

检查器逐行验证 Question、嵌入式 Asset package、来源页和逻辑资产双向关系，并要求
`review.md` 使用 `Question ID | Source | Page | Issue | Required decision` 固定表格。
跨项目本地二进制内容使用 `base64` 或 data URI，禁止把来源目录路径传给题库 MCP。

### 3.2 来源与准备

| ID | 需求 |
| --- | --- |
| S2Q-001 | 开始前确认来源项目、目标题库、来源位置、写入授权和验收范围。 |
| S2Q-002 | 原资料保持只读，中间产物只写入当前来源项目的隔离工作区。 |
| S2Q-003 | 记录来源文件的稳定相对路径或内容标识，不把本机绝对路径写入交换数据。 |
| S2Q-004 | 盘点页码、题号、答案册、分类表、公式、图片、跨页结构和明显缺页。 |
| S2Q-005 | 在生成 JSONL 前读取目标题库的实时 Question 与 Asset Schema。 |
| S2Q-006 | 只向用户询问无法从来源或题库发现、且会改变结果的判断。 |

### 3.3 MinerU 与 AI 整理

| ID | 需求 |
| --- | --- |
| S2Q-010 | 使用已有 MinerU 输出；Skill 不安装、启动或升级 MinerU。 |
| S2Q-011 | MinerU 输出只作为证据与草稿，不直接视为正确题目。 |
| S2Q-012 | AI 识别题目边界、共享题干、子问、选项、答案、解析、公式和图片归属。 |
| S2Q-013 | 依赖共享题干的子问默认保留为一个复合题；仅拆分可独立理解和作答的单元。 |
| S2Q-014 | 只修正来源能够明确证明的 OCR 错误；不确定字符、上下标、符号、单位和公式进入复核。 |
| S2Q-015 | 答案册只有在文档身份、年份、题号和对应关系明确时才能自动关联。 |
| S2Q-016 | AI 推断必须与来源原文区分；不得生成来源中不存在的答案、条件或出处。 |

### 3.4 JSONL、分类与来源证据

| ID | 需求 |
| --- | --- |
| S2Q-020 | `questions.jsonl` 每行只包含现有 Question Schema 允许的字段。 |
| S2Q-021 | 每题至少保留来源文件、页码或页码范围；存在原题号时同时保留原题号。 |
| S2Q-022 | 来源位置写入现有 `source.reference` 或 `review_notes_md`，不新增 Schema 字段。 |
| S2Q-023 | 对用户不关心但 Schema 必填的属性，使用经确认的项目常量或保守回退，并说明其非语义含义。 |
| S2Q-024 | 分类只使用用户提供的分类表、题库现有 taxonomy 或已确认映射。 |
| S2Q-025 | 未匹配或冲突分类进入 `review.md`，不得静默创建 canonical tag。 |
| S2Q-026 | 标题可以是便于检索的简短生成标签，但不得冒充原题标题。 |
| S2Q-027 | 未确认的题目、答案、公式、图片或分类必须保持 `draft`。 |
| S2Q-028 | `review.md` 的每一项都指向题目 ID、来源页和一个可执行的复核问题。 |

### 3.5 图片与 Asset package

| ID | 需求 |
| --- | --- |
| S2Q-030 | 只提取题目实际引用的图片，并保留理解图片所需的标注、坐标轴、图例和上下文。 |
| S2Q-031 | 每个逻辑资产包使用现有 Asset Schema，不引入新的资产格式。 |
| S2Q-032 | 原始裁图、可编辑源和渲染表示必须标明各自用途，不得把 AI 重绘冒充原图。 |
| S2Q-033 | 题目中的资产引用与 package 中的逻辑 ID 必须一致。 |
| S2Q-034 | 图片归属、裁剪范围或语义不确定时保留原页证据并写入 `review.md`。 |
| S2Q-035 | MinerU、AI 和来源脚本不得直接写题库资产 manifest 或受管资产目录。 |
| S2Q-036 | 外部 URL 继续遵循 qbank 现有警告策略，不由数字化 Skill 自动下载。 |
| S2Q-037 | 在题目 prepare 前先确认其依赖的资产已成功提交并通过验证。 |
| S2Q-038 | 缺失或失败的资产不得被无提示地从题目声明或正文引用中删除。 |

### 3.6 MCP 写入与验证

| ID | 需求 |
| --- | --- |
| S2Q-040 | 所有正式写入使用现有 MCP，不让 MinerU、AI 或脚本直接修改权威文件。 |
| S2Q-041 | 写入严格遵循 `prepare → inspect → commit → validate`。 |
| S2Q-042 | 资产使用 `asset_ingest_prepare`，题目使用 `ingest_prepare`，提交使用 `operation_commit`。 |
| S2Q-043 | prepare 后检查字段 diff、diagnostics、warning 和 `repository_revision`。 |
| S2Q-044 | commit 前仓库 revision 变化时放弃旧 operation 并重新 prepare。 |
| S2Q-045 | 提交后使用 `question_validate` 验证题目和资产诊断，并记录已提交 ID、warning 与待复核项。 |
| S2Q-046 | 默认按小批次提交；复杂公式、图片或来源变化明显时进一步缩小批次。 |
| S2Q-047 | 题目与资产当前不是跨 operation 原子事务；必须按依赖顺序提交并明确报告部分成功。 |
| S2Q-048 | prepare 或校验失败时修正交换文件后重试，不直接修补 Markdown、manifest 或 SQLite。 |

## 4. 方向 B：qbank → 正式交付物

### 4.1 最小工作区

```text
build/deliver/<job-name>/
├─ selection.yaml
├─ snapshot/
│  ├─ questions.jsonl
│  └─ assets/
├─ content.tex
└─ output/
   └─ <variant>/
      ├─ <job>-<variant>.pdf
      └─ build-summary.json
```

`$qbank-deliver` 提供原创、无特定学校品牌的 `qbank-zh-exam-v1` 固定模板，而不是由
AI 每次重新设计。`selection.yaml`
记录所选题目、顺序、内容版本和必要版式参数；它暂时是项目侧文件约定，不是新的 Paper
Schema。`content.tex` 和 `output/` 都是可重建产物。

完成 MCP 读取快照和受限 `content.tex` 后运行：

```powershell
python .agents/skills/qbank-deliver/scripts/build_delivery.py build/deliver/<job-name> `
  --qbank-root <qbank-root>
```

脚本重新检查当前 repository revision、Question 顺序、资产 manifest、containment、符号链接
和哈希，然后以固定参数调用 `latexmk`/XeLaTeX。成功输出 PDF 与
`build-summary.json`；失败不替换上次成功的 `output/<variant>/`，三个版本可同时保留。
`--validate-only` 只读校验契约，不写入交付工作区。
构建器禁用 shell escape，仅接受 qbank 宏与明确的常用数学命令白名单，并拒绝 TeX
注释、`^^` 编码、内部或未知命令以及符号链接或 Windows reparse-point 输出目录，避免
受限宏和工作区边界被绕过。

仓库内的完全合成示例可在一个新目录中执行完整 MCP 入库、查询、快照和构建：

```powershell
python examples/workflows/lightweight/run_demo.py build/workflows/lightweight-demo
```

没有 XeLaTeX 时可追加 `--skip-tex`，仅生成并验证快照与构建摘要。

### 4.2 查询、选择与冻结

| ID | 需求 |
| --- | --- |
| Q2D-001 | 使用现有 `question_search` 进行广泛发现，再对候选 ID 调用 `question_get`。 |
| Q2D-002 | 选择条件、人工决定和排除理由由 AI/Skill 显式写入 `selection.yaml`，不得依赖隐藏筛选。 |
| Q2D-003 | `selection.yaml` 至少记录目标题库、repository revision、题目 ID、顺序和交付版本。 |
| Q2D-004 | 构建前重新读取入选题目；revision 变化时停止并重新确认选择。 |
| Q2D-005 | `draft`、缺答案或资产未就绪的题目按交付用途阻断或明确警告。 |
| Q2D-006 | 学生版、答案版和解析版复用同一题目顺序与编号。 |

### 4.3 TeX 生成与固定模板

| ID | 需求 |
| --- | --- |
| Q2D-010 | AI 与 Skill 只生成受控 `selection.yaml`、正文片段和 TeX，不修改 qbank。 |
| Q2D-011 | 页面、字体、页眉页脚、题号、分值、答案空间和常用环境由固定模板定义。 |
| Q2D-012 | 模板具有明确名称和版本，并与需要的 TeX engine、宏包和字体一起记录。 |
| Q2D-013 | 来源文本作为 TeX 内容转义或通过受控模板参数插入，不得拼接成 shell 命令。 |
| Q2D-014 | 数学内容保持可编辑 TeX；仅在无法可靠转写时使用带来源的图像。 |
| Q2D-015 | 逻辑资产解析为确定的本地表示并复制到隔离构建目录。 |
| Q2D-016 | 远程资源不得在正式构建时静默下载。 |
| Q2D-017 | 缺失字体、宏包、TeX engine 或资产时给出明确诊断，不留下看似成功的半成品。 |
| Q2D-018 | AI 不得在答案版或解析版中补造题库缺失的答案和解析。 |

### 4.4 构建、检查与产物

| ID | 需求 |
| --- | --- |
| Q2D-020 | 默认使用 `latexmk` 调用 XeLaTeX；项目可显式选择已验证的其他固定工具链。 |
| Q2D-021 | 构建在隔离目录执行，并使用参数数组、固定工作目录和明确编码。 |
| Q2D-022 | 构建过程只读 qbank，不修改题目、资产、Paper、历史、索引或 MCP operation。 |
| Q2D-023 | 失败构建不覆盖最后一个成功产物。 |
| Q2D-024 | 至少检查 TeX 成功退出、PDF 可打开、页数合理、文本可提取、公式和图片存在。 |
| Q2D-025 | 学生版必须检查答案、解析、rubric 和审阅信息没有泄露。 |
| Q2D-026 | 高风险正式文档保留必要人工抽查，但当前不建设通用逐页验收平台。 |
| Q2D-027 | 输出旁记录选择文件、模板版本、题库 revision、工具版本、warning 和 SHA-256；无需完整 `BuildManifest`。 |

## 5. Skill、CLI、Studio 与 MCP 的职责

| 组件 | 当前职责 | 本方案明确不做 |
| --- | --- | --- |
| `$qbank-digitize` | 检查 MinerU 结果、制定字段策略、整理交换文件、收敛复核项 | 运行 OCR、维护 Candidate 数据库、直接写题库 |
| `$qbank` | 建立题库上下文、读取 Schema、提供确定性操作指导 | 承担来源语义判断 |
| MCP | 查询、取题、prepare、commit、validate | OCR、任意脚本、TeX 构建、新工具 |
| Studio | 审阅和修订已入库题目与资产 | 通用 OCR 作业控制台 |
| `$qbank-deliver` | 冻结 selection/快照、生成受限 TeX 并调用固定工具链 | 改写权威题库 |

MCP 不可用或 degraded 时，本工作流暂停正式 agent 写入；若用户明确选择 CLI 兼容路径，
则由 `$qbank` 按同样的 dry-run、检查和校验边界执行，不降低安全要求。

## 6. 失败与恢复

- MinerU 失败：保留其日志和已有输出，修复来源侧问题后重跑；qbank 不产生写入。
- JSONL 或资产非法：MCP prepare 拒绝，修正中间文件后重新 prepare。
- revision 冲突：取消或丢弃旧 operation，重新读取和 prepare。
- 资产成功、题目失败：明确报告部分成功；修正题目并重新提交，不删除已验证且仍需要的资产。
- 索引同步失败：遵循 qbank 现有 dirty-marker 和 rebuild 策略，不回滚权威 Markdown。
- TeX 构建失败：保留诊断，不覆盖成功产物，也不修改题库。
- 来源无法确认：题目保持 `draft`，问题进入 `review.md`，不得以猜测完成批次。

## 7. 验收

轻量方案达到可用状态需要以下证据：

1. 使用公开合成资料和预制 MinerU 输出完成一次端到端整理。
2. `questions.jsonl` 与 Asset packages 通过实时 Schema 和 MCP prepare。
3. `review.md` 只含真实不确定项，且每项可定位到题目和来源页。
4. 正式写入只经过现有 MCP 两阶段操作，提交后全库校验通过。
5. 从 MCP 查询/取题生成 `selection.yaml` 和 TeX。
6. 固定模板通过 `latexmk` / XeLaTeX 生成可读 PDF，公式、图片和内容变体正确。
7. 来源脚本、MinerU 和交付构建均未直接修改 qbank 权威文件。
8. 不需要新的 qbank Schema、MCP 工具、核心重构、服务或数据库。

## 8. 远期可选方案

以下内容不是当前目标、承诺或实现前提：

- `CandidateBlock` 或其他通用 OCR 候选模型；
- `DigitizationDecisionPacket` 或持久化审批对象；
- `DeliveryProfile` 公共 Schema；
- 完整 `BuildManifest`；
- 作业状态、调度、断点续跑和多用户审阅平台；
- 自动逐页出版验收、通用模板设计器或 qbank 内置 PDF 后端。

只有多个独立项目证明轻量文件约定不足，并形成稳定、可复用需求后，才为其中某项新建
feature 文档和 ADR。任何提案仍不得默认改变 qbank 的权威数据边界。

另见[功能契约](../features/source-qbank-deliverables.md)和
[qbank 路线图](roadmap.md)。
