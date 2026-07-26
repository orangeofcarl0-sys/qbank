# qbank 用户指南

[English](../en/user-guide.md) · [中文文档](README.md)

本文说明 qbank `0.3.0-beta.2` 的项目结构、数据边界和主要命令行工作流。数据 Schema
仍为 `1.0`；完整参数以各命令的 `--help` 输出为准。安装与升级见
[安装指南](installation.md)。

## 项目结构

`qbank init [DIR]` 创建本地题库。程序从当前目录向上查找 `qbank.yaml`，因此可在项目任意
子目录运行命令。

| 路径 | 用途 | 数据性质 |
| --- | --- | --- |
| `questions/` | 题目 Markdown | 权威数据 |
| `assets/` | 本地资源和逻辑资产 manifest | 权威数据 |
| `taxonomy.yaml` | 标签注册表 | 权威数据 |
| `views.yaml` | 保存的查询视图 | 权威数据 |
| `papers/` | 试卷定义 | 用户维护数据 |
| `templates/` | 试卷模板和可选 reference DOCX | 用户维护数据 |
| `.qbank/history/` | 权威写入摘要 | 与 Markdown 同步提交 |
| `.qbank/index.sqlite` | 全文检索投影 | 可重建数据 |
| `build/` | 临时构建和 AI 交换文件 | 可删除数据 |
| `exports/` | 最终导出产物 | 可重建产物 |

初始化会先做完整冲突预检。任一受管文件已存在时以退出码 5 结束且零写入；只有显式
`--force` 才允许覆盖初始化资源。

```powershell
qbank init demo-bank
Set-Location demo-bank
qbank doctor --format json
```

## 题目格式与 Schema

题目位于 `questions/<subject>/<ID>.md`。YAML front matter 保存短元数据，正文按固定顺序保存
题目、选项、答案、解析、评分要点和审阅备注。`schema_version`、非空题干和至少一个有效主题
是模型约束。

创建交换数据前读取相应 Schema：

```powershell
qbank schema --kind question --format json
qbank schema --kind paper --format json
qbank schema --kind patch --format json
qbank schema --kind asset-package --format json
```

JSON 和 JSONL 是交换格式，不是第二份权威题库。时间字段必须包含时区并会规范化为 UTC。

## 权威写入流程

除初始化外，题目、标签、视图和资产写入均先 dry-run，再应用完全相同的正式操作，最后校验。

```powershell
qbank ingest build\ai\source.jsonl --dry-run --format json
qbank ingest build\ai\source.jsonl --format json
qbank validate --format json
```

批量导入默认全有或全无。仅在明确接受跳过坏行时使用 `--continue-on-error`；结果中的
`line`、`skipped` 和诊断字段用于定位输入问题。结构化修订使用 patch：

```powershell
qbank patch OPT-INT-0001 --file build\ai\OPT-INT-0001.patch.json `
  --dry-run --format json
qbank patch OPT-INT-0001 --file build\ai\OPT-INT-0001.patch.json --format json
qbank validate --format json
```

不得用普通写入或 `--upsert` 覆盖无法解析的 Markdown。此类文件必须先人工修复，或在明确
确认 ID 后删除。

## 查询与全文检索

结构化查询按学科、章节、主题、题型、状态、年份和难度筛选仓储快照：

```powershell
qbank query --subject optics --status reviewed `
  --fields id,title,subject,chapter,topics,type,difficulty,status `
  --format json
qbank search "光程差" --format json
qbank get OPT-INT-0001 --format json
```

两字符以下或包含短词的搜索使用参数化 SQLite `LIKE` 回退，较长搜索使用 trigram FTS5。
只读搜索不会创建索引；索引缺失、损坏、过期或 dirty 时会明确失败。

## 标签与保存视图

`taxonomy.yaml` 保存规范 slug、显示名、别名、颜色、说明和父标签，不保存题目与标签关系；
该关系仅来自题目 Markdown 的 `topics`。

```powershell
qbank tag list --format json
qbank tag stats --format json
qbank tag cooccur --top-n 12 --format json
qbank tag rename old-slug canonical-slug --dry-run --format json
qbank tag rename old-slug canonical-slug --format json
qbank validate --format json
```

重命名、合并、删除和规范化把 taxonomy、题目 Markdown 与历史作为一个权威提交单元。
`views.yaml` 只保存组合筛选，不改变题目或形成不可见约束。

## 本地资源与逻辑资产

普通本地图片必须使用题库相对路径、位于配置的 assets 目录、实际存在，并同时出现在正文
引用和 YAML `assets` 声明中。HTTP、HTTPS 和协议相对 URI 允许但产生 warning；绝对路径、
`file:`、`data:` 和越界路径会被拒绝。

逻辑资产用稳定 ID 管理原始参考、可编辑源和 PDF/SVG/PNG 表示。新 Markdown 使用
`qbank-asset:<asset-id>`，TeX 使用 `\qbankasset{<asset-id>}`。

```powershell
qbank asset show OPT-INT-0001 figure-1 --format json
qbank asset ingest OPT-INT-0001 build\ai\asset-package.json --dry-run --format json
qbank asset ingest OPT-INT-0001 build\ai\asset-package.json --format json
qbank asset render OPT-INT-0001 figure-1 --dry-run --format json
qbank asset render OPT-INT-0001 figure-1 --format json
qbank asset validate --format json
```

替换按内容哈希追加版本，不覆盖旧表示。Ipe 编辑、重新渲染、首选表示和 final 状态均为显式
操作；外部资源不会自动下载。

## 组卷、导出与预览

试卷定义保存于 `papers/`，自动生成的定义建议放在 `papers/generated/`。先验证再构建：

```powershell
qbank paper validate papers\generated\optics-test.yaml --format json
qbank paper build papers\generated\optics-test.yaml --format md `
  --output exports\optics-test-student.md
qbank paper build papers\generated\optics-test.yaml --format md `
  --with-solutions --output exports\optics-test-solutions.md
```

成对布尔参数可双向覆盖试卷默认值：`--with-answers/--without-answers`、
`--with-solutions/--without-solutions`、`--with-rubric/--without-rubric` 和
`--show-ids/--hide-ids`。

```powershell
qbank export --subject optics --status reviewed --format jsonl `
  --output exports\optics-reviewed.jsonl
qbank preview
```

DOCX 由系统 Pandoc 生成。缺失时 DOCX 构建以退出码 7 失败，Markdown 和 HTML 不受影响。
`qbank preview --serve` 和 `qbank desktop` 是交互式阻塞命令，不得由无人值守自动化启动。

## 诊断与索引维护

```powershell
qbank status --format json
qbank doctor --format json
qbank validate --format json
qbank index rebuild --format json
```

索引只在权威提交后更新。同步失败时 Markdown 保持成功，程序写入 `.qbank/index.dirty` 并
返回 warning；成功整体重建后清除 marker。配置为禁用的索引不视为 dirty。

## 退出码

| 代码 | 含义 |
| ---: | --- |
| 0 | 成功 |
| 1 | 一般错误或项目不存在 |
| 2 | CLI 参数错误 |
| 3 | 数据、题目、查询或试卷校验失败 |
| 4 | 题目不存在 |
| 5 | 冲突或重复 ID |
| 6 | 导出失败 |
| 7 | Pandoc 等外部依赖缺失 |
