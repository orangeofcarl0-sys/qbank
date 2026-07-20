# qbank

`qbank` 是一个本地优先、对人类和 AI 都友好的题库命令行工具。每道题以一个带
YAML front matter 的 Markdown 文件保存；JSON/JSONL 用于 AI 交换；SQLite FTS5
只是随时可删除重建的搜索索引；`paper.yaml` 是可审查的组卷结果。

它不提供在线考试、用户账号、学习记录、自动判题、OCR、内置 AI 或网络服务。

## 安装与开发

需要 Python 3.11 或更高版本。在 Windows PowerShell 中：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
qbank --help
```

Windows PowerShell 5.x 把文本传给原生命令前，请先将管道设为 UTF-8；读取 JSON 时也
显式指定 UTF-8，避免中文被系统代码页改写：

```powershell
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
```

也可用 `pip install -r requirements-dev.lock` 复现已验收的开发依赖版本，再执行
`pip install -e . --no-deps --no-build-isolation` 安装本项目。锁文件覆盖运行、开发和
构建依赖；更新依赖后，在干净虚拟环境中安装 `.[dev]`，再用
`python -m pip freeze --exclude-editable > requirements-dev.lock` 重建。也可使用
`python -m qbank`。开发检查：

```powershell
ruff format .
ruff check .
pyright
lint-imports
deptry .
pytest --cov=qbank --cov-branch --cov-fail-under=0 --cov-report=json:build/audit/coverage.json
python scripts/check_branch_coverage.py build/audit/coverage.json
pip check
pip-audit
python -m pip wheel . --no-deps --no-build-isolation
```

## 初始化

`qbank init` 初始化当前目录，`qbank init demo-bank` 初始化指定子目录。命令会创建
`questions/`、`assets/`、`papers/`、`templates/`、`exports/`、`build/`、
`schemas/`、`AGENTS.md`、`.agents/skills/qbank/` 和 `.qbank/history/`，并建立空的
FTS5 索引。程序从当前目录向上查找
`qbank.yaml`，所以可以在任意子目录运行命令。

初始化采用冲突即失败：任何将由 qbank 管理的同名文件已存在时，命令以退出码 5
结束且不会写入任何文件。只有显式 `--force` 才会覆盖这些受管文件。

```powershell
qbank init demo-bank
Set-Location demo-bank
qbank doctor --format json
```

初始化会写入一个自制 SVG 示例资源和可用的 `papers/demo-paper.yaml`，但不会把示例
题自动导入。仓库中的 `examples/questions.jsonl` 提供 8 道覆盖主要题型的示例。

常规初始化内容的权威来源位于安装包的 `qbank.resources` 中，包括默认配置、两个
试卷模板、示例试卷、SVG 和预览内部模板。仓库根部的 `templates/` 与
`papers/demo-paper.yaml` 只是便于阅读的逐字节镜像；修改默认内容时应先修改包内资源，
再同步镜像并运行测试。仓库级 `.agents/skills/qbank/` 是 Codex Skill 的规范来源，
并逐字节同步到初始化包资源。JSON Schema 始终直接由 Pydantic 模型生成，不维护手写
副本。

## 数据格式

题目源文件必须位于 `questions/<subject>/<ID>.md`，文件名与 ID 一致。YAML 只保存
短元数据；长文本位于固定章节 `题目`、`选项`、`答案`、`解析`、`评分要点` 和
`审阅备注`。保存时按此顺序规范化；读取时允许缺少非必需章节。

原始 HTML 被明确禁用：Markdown 渲染器会将其转义，避免题目内容向预览或导出页面
注入脚本。公式通过 MathJax CDN 渲染；完全离线时普通文本与本地图片仍可查看，但公式
只显示 TeX 源文本。

本地图片必须使用题库相对路径、位于配置的 `assets` 目录、实际存在，并同时列在
题目 YAML 的 `assets` 与 Markdown 图片引用中。HTTP、HTTPS 及 `//host` 图片允许，
但校验与构建会发出 `external_asset` 警告；绝对路径、`file:`、`data:` 和越界路径
会被拒绝。

Jinja 模板在沙箱环境中执行，但模板文件仍属于题库的可信代码边界：只应使用自己
编写或审查过的 `templates/paper.md.j2` 与 `templates/paper.html.j2`，不要直接运行
来源不明的模板。

Markdown 是唯一题目源数据。`.qbank/index.sqlite` 可以安全删除，再用
`qbank index rebuild` 重建。所有真实写操作在 `.qbank/history/` 留下 JSON 摘要；
仍建议用 Git 管理完整版本历史。

`status`、`doctor`、`search` 和索引更新时间读取使用 SQLite 只读连接，不会创建
`.qbank`、数据库、表或 dirty marker。索引缺失、损坏或存在 dirty marker 时，
`search` 会以退出码 3 明确失败并提示执行 `qbank index rebuild`；`doctor` 报告 FAIL，
`status.index_dirty` 为 `true`。已禁用索引不视为 dirty；已确认 stale 的投影也会由
`status` 和 `doctor` 报告。

## 内部架构与维护

完整边界、审查规则、兼容策略和决策记录见
[`docs/architecture.md`](docs/architecture.md)、
[`docs/code_review.md`](docs/code_review.md)、
[`docs/compatibility-policy.md`](docs/compatibility-policy.md) 与
[`docs/adr/`](docs/adr/)。

内部依赖方向固定为“CLI → 应用服务 → 领域模型”，基础设施通过
`qbank.bootstrap` 组合根注入应用端口。每条命令只解析一次不可变 `ProjectContext`；每个用例通过
`MarkdownQuestionRepository` 生成一次 `RepositorySnapshot`，其中同时保留合法题目、
损坏源、身份提示和重复 ID，供校验、查询、组卷、预览与诊断复用。

SQLite 字段由唯一的 `IndexDocument` 投影定义。Markdown 与 history 是可回滚的权威
提交单元，索引只在其后以单一事务同步；索引同步失败不会撤销 Markdown，而会留下
dirty marker。`AssetService` 和 `RenderService` 统一资源分类、复制、MarkdownIt
图片路径重写、禁用原始 HTML 与 Jinja 沙箱策略。

维护默认资源或内部边界后应运行完整质量门：

```powershell
ruff format --check .
ruff check .
pyright
lint-imports
deptry .
pytest --cov=qbank --cov-branch --cov-fail-under=0 --cov-report=json:build/audit/coverage.json
python scripts/check_branch_coverage.py build/audit/coverage.json
pip check
pip-audit
python -m pip wheel . --no-deps --no-build-isolation
python -m qbank --help
```

## Codex 原生接入

每个新题库都包含简短的 `AGENTS.md` 和仓库级 `$qbank` Skill。适用于 Codex CLI、
Codex desktop、IDE extension 和 Windows PowerShell；qbank 仍是纯本地工具，不需要
OpenAI API key，也不调用任何大模型 SDK。

先检查 Skill、运行环境和工作流命令：

```powershell
qbank codex check --format json
qbank codex instructions --format markdown
qbank codex instructions --format json
```

`codex check` 检查 AGENTS、Skill frontmatter、qbank 可执行性、当前目录、Codex CLI
以及工作流命令。Codex CLI 不在 PATH 时只产生 WARN，不会使 qbank 自身失败。
`codex instructions` 输出稳定的规则、推荐命令序列和数据路径。

如需让其他仓库也发现同一个 Skill，可先查看计划，再确认安装到当前用户目录：

```powershell
qbank codex install-skill --user --dry-run
qbank codex install-skill --user
# 自动化环境中显式授权：
qbank codex install-skill --user --yes
```

目标路径是 `$HOME/.agents/skills/qbank/`。命令未经确认不会写用户目录，也不会覆盖内容
不同的现有 Skill。题目写入仍须先 dry-run，临时 AI 交换文件写入 `build/ai/`，生成的
试卷定义写入 `papers/generated/`，最终产物写入 `exports/`。

0.1.0 不实现 MCP Server。业务逻辑位于独立 service layer，未来可用同一服务实现
`qbank mcp`，并通过以下方式注册本地 STDIO 服务：

```powershell
codex mcp add qbank -- qbank mcp
```

该命令只是未来边界说明，当前版本不要执行。

## AI 工作流

读取机器可用 Schema：

```powershell
qbank schema --format json
qbank schema --kind paper --format json
qbank schema --kind patch --format json
qbank schema --kind asset-package --format json
```

## 逻辑资产与 Ipe 工作包

题目 Markdown 仍是唯一的题目正文权威来源，但现在可以引用稳定逻辑资产 ID，
例如 `asset:question-figure` 或固定 representation `asset:question-figure#render-svg`。
每个逻辑资产由 `assets/<QUESTION_ID>/<ASSET_ID>/asset.yaml` 描述，并可以同时保留
原始参考图、Base64 解码文件、远程 URL、PDF 裁剪元数据、TikZ、可编辑 Ipe 与
PDF/SVG/PNG 渲染版本。旧的 `assets/...` 字符串路径仍可读取；确认后可使用
`qbank asset normalize` 将带有已保存来源关系的旧引用迁移为逻辑 ID。

电子化项目只输出 `asset-package.json`，qbank 负责规范化、哈希、复制、生命周期、
选择和历史记录。导入前先执行演练，随后执行真实写入：

```powershell
qbank asset ingest ZJU841-2005-CALC-06 .\asset-package.json --dry-run --format json
qbank asset ingest ZJU841-2005-CALC-06 .\asset-package.json --format json
qbank asset validate --format json
qbank asset show ZJU841-2005-CALC-06 question-6 --format json
```

可直接添加本地文件、Base64/data URI、内联 TikZ、HTTP(S) URL、PDF 页/裁剪元数据和
Ipe 文件。`replace` 永远新增哈希版本，绝不覆盖旧表示；`render` 只通过已发现或已配置
的 Ipe 可执行文件生成 PDF/SVG/PNG，并且失败不会报告为成功。

```powershell
qbank asset edit ZJU841-2005-CALC-06 question-6 --dry-run --format json
qbank asset render ZJU841-2005-CALC-06 question-6 --dry-run --format json
qbank asset render ZJU841-2005-CALC-06 question-6 --format json
qbank asset set-render ZJU841-2005-CALC-06 question-6 render-svg-<hash> --format json
qbank asset finalize ZJU841-2005-CALC-06 question-6 --format json
```

`assets.editors.ipe.command`、`assets.renderers.ipe.iperender` 与
`assets.renderers.ipe.ipetoipe` 可指定 Windows Ipe 路径；未配置时会在 PATH 和常见
`E:/Tool/ipe-*/bin` 目录中发现。Ipe、系统打开和文本编辑器都只接受已登记、受题库
containment 校验的 representation，绝不把网页或 CLI 输入作为 shell 命令执行。

运行 `qbank preview --serve` 会先构建静态预览，再仅绑定 `127.0.0.1` 的资产管理页。
该页显示原始图、当前预览、所有表示、来源、状态和衍生关系；按钮通过带本地随机令牌与
same-origin 校验的 HTTP API 调用 qbank 服务，实际执行打开、编辑、重新渲染、替换、选择
和定稿。静态 `qbank preview` 页面不伪装这些本地操作按钮。

试卷构建只复制最终渲染正文实际引用的资源：学生版不会把仅出现在答案或解析中的图形
列入产物资源清单，答案版则会按其可见内容补齐这些资源。

添加一题（JSON 字段与 `qbank get ID --format json` 对称）：

```powershell
Get-Content .\question.json -Raw -Encoding utf8 |
  qbank add --stdin --format json
```

先验证再批量导入 JSONL。默认全批预检；任何记录失败时不会写入部分结果：

```powershell
qbank ingest ..\examples\questions.jsonl --dry-run --format json
qbank ingest ..\examples\questions.jsonl --format json
qbank ingest .\updates.jsonl --upsert --format json
qbank ingest .\mixed.jsonl --continue-on-error --format json
```

JSONL 按物理行独立解析，结果包含 `line` 和 `skipped`。默认任何一行失败都会零写入；
`--continue-on-error` 才会跳过坏行并以一个事务写入其余有效记录。

查询和全文搜索：

```powershell
qbank query `
  --subject optics `
  --topic interferometry `
  --difficulty-min 1 `
  --difficulty-max 3 `
  --status reviewed `
  --fields id,title,type,difficulty,topics `
  --format json

qbank search "Michelson 光程差" --format json
qbank get OPT-INT-0001 --format json
```

多个 `--topic` 默认是 AND；用 `--topic-mode or` 改为 OR。

结构化修改先 dry-run，再正式写入：

```powershell
Get-Content ..\examples\patch.json -Raw -Encoding utf8 |
  qbank patch OPT-INT-0001 --stdin --dry-run

Get-Content ..\examples\patch.json -Raw -Encoding utf8 |
  qbank patch OPT-INT-0001 --stdin
```

Patch 不能修改 ID、时间戳或未知字段；修改后会重新经过完整校验。

## 组卷

AI 只需按 `schemas/paper.schema.json` 生成 `paper.yaml`，列出分区、题目 ID 和分值。
先验证，再构建学生版或答案版：

```powershell
qbank paper validate papers\demo-paper.yaml --format json
qbank paper build papers\demo-paper.yaml --format md
qbank paper build papers\demo-paper.yaml --format html
qbank paper build papers\demo-paper.yaml --format md --with-solutions `
  --output build\demo-paper-solutions.md
```

`--with-solutions` 会自动包含答案。成对参数
`--with-answers/--without-answers`、`--with-solutions/--without-solutions`、
`--with-rubric/--without-rubric` 和 `--show-ids/--hide-ids` 可双向覆盖
`paper.yaml` 的默认选项。HTML/Markdown 输出会复制所需 assets。

DOCX 由系统 Pandoc 生成：

```powershell
qbank paper build papers\demo-paper.yaml --format docx
```

如果 Pandoc 不存在，Markdown 和 HTML 不受影响；DOCX 命令返回清晰错误和退出码 7，
`qbank doctor` 返回 WARN。可将自定义 Pandoc reference DOCX 放到
`templates/reference.docx`；文件缺失时使用 Pandoc 默认样式。

## 普通导出与预览

普通导出处理筛选结果，不包含试卷分区或分值：

```powershell
qbank export --subject optics --status reviewed --format jsonl `
  --output exports\optics-reviewed.jsonl
```

支持 `json`、`jsonl`、`md`、`html` 和 `txt`。纯文本导出通过统一导出器注册表实现；
静态预览无需服务器：

```powershell
qbank preview
Start-Process build\preview\index.html
qbank preview --serve
```

预览支持前端全文搜索及 subject、type、status、difficulty 筛选，答案与解析默认折叠。

## 命令速查

| 命令 | 用途 |
| --- | --- |
| `qbank init [DIR]` | 初始化题库 |
| `qbank status` | 数量、状态、题型和索引摘要 |
| `qbank doctor` | 环境与完整性诊断 |
| `qbank schema [--kind question\|paper\|patch\|asset\|asset-package]` | 输出 JSON Schema |
| `qbank add` / `qbank ingest` | 单题或 JSONL 批量导入 |
| `qbank validate [ID] [--changed]` | 校验题库 |
| `qbank list` / `get` / `query` | 读取和筛选 |
| `qbank search` | SQLite FTS5 全文搜索 |
| `qbank patch` / `delete` | 结构化修改或删除 |
| `qbank index rebuild` | 完整重建索引 |
| `qbank preview` | 生成静态浏览页 |
| `qbank asset list\|show\|ingest\|add\|open\|edit\|render\|replace\|set-render\|set-editor\|finalize\|normalize\|validate` | 管理多表示逻辑资产 |
| `qbank export` | 导出查询结果 |
| `qbank paper validate` / `build` | 校验和构建试卷 |
| `qbank codex check` / `instructions` | 检查并输出 Codex 仓库规则 |
| `qbank codex install-skill` | 经确认安装用户级 qbank Skill |

所有命令都有 `--help`。面向自动化的命令提供 `--format json` 或 JSONL 输出；正式结果
写 stdout，诊断写 stderr。

## 退出码

| 代码 | 含义 |
| ---: | --- |
| 0 | 成功 |
| 1 | 一般错误或项目不存在 |
| 2 | CLI 参数错误 |
| 3 | 数据、题目或试卷校验失败 |
| 4 | 题目不存在 |
| 5 | 冲突或重复 ID |
| 6 | 导出失败 |
| 7 | Pandoc 等外部依赖缺失 |

## 当前限制

- LaTeX 只做定界符、美元符号和花括号的轻量检查，不执行 TeX 编译。
- 单选/多选答案检查识别常见的 `A.`、`B)` 等标签，不试图理解任意自然语言答案。
- HTML 预览使用 CDN MathJax；离线时不渲染公式。
- Markdown 与历史记录作为一个可回滚的权威提交单元；索引更新发生在其后。索引失败
  不撤销源文件，而会写入 `.qbank/index.dirty`，由 `status`/`doctor` 报告，成功执行
  `qbank index rebuild` 后清除。
- `--changed` 依赖可用的 Git 工作区；否则安全地回退为全量校验。
