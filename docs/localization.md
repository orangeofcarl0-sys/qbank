# 文档本地化策略 / Documentation localization policy

## 目标 / Goal

qbank 为公开用户文档提供简体中文（`zh-CN`）和英文（`en`）版本。翻译应表达相同的产品事实、
安全边界和失败行为；不要求逐句直译。

qbank provides public user documentation in Simplified Chinese (`zh-CN`) and English (`en`).
Translations must communicate the same product facts, safety boundaries, and failure behavior;
sentence-by-sentence equivalence is not required.

## 受管范围 / Managed scope

以下内容必须成对维护：语言首页、用户指南、CLI 参考、Studio 指南、Codex/MCP 接入、兼容性
策略、冻结兼容性基线和当前版本已知限制。根目录 `README.md` 与 `README.en.md` 也构成一对。

The following must be maintained as locale pairs: locale index, user guide, CLI reference, Studio
guide, Codex/MCP integration, compatibility policy, frozen compatibility baseline, and
current-release known limitations. The root
`README.md` and `README.en.md` also form a pair.

架构、ADR、代码审查、UI 设计研究和历史分析属于维护者资料，可保留原始工作语言。若其中的
内容成为用户契约，必须同步进入受管的双语用户文档。

Architecture, ADRs, code-review guidance, UI design research, and historical analysis are
maintainer material and may retain their working language. If any of their content becomes a user
contract, it must also be reflected in the managed bilingual user documentation.

## 编写规则 / Authoring rules

1. 每个本地化页面顶部提供语言切换和返回文档首页的链接。
2. 文件名、命令、选项、字段、诊断码和 Schema 标识不翻译。
3. 示例只使用自制公开数据，不包含本机路径、身份、凭据或真实试题。
4. 面向用户的行为变更在同一变更中更新两种语言；不能用空白模板满足检查。
5. 翻译存在暂时差异时，以代码、Schema 和兼容性基线为事实来源，并在合并前修正两种语言。

1. Every localized page provides language switching and a link back to the documentation home.
2. File names, commands, options, fields, diagnostic codes, and Schema identifiers are not translated.
3. Examples use only self-authored public data and contain no machine paths, identities, credentials,
   or real examination questions.
4. A user-visible behavior change updates both languages in the same change; empty boilerplate does
   not satisfy the gate.
5. If translations temporarily disagree, code, Schema, and the compatibility baseline are the factual
   sources, and both languages must be reconciled before merge.

## 自动门禁 / Automated gate

`python scripts/check_docs_sync.py` 验证受管文件成对存在、语言导航完整、本地链接有效、两种
CLI 参考覆盖当前命令树、README 安全示例可执行且公开文本不含私有数据。失败会阻止发布。

`python scripts/check_docs_sync.py` verifies paired files, language navigation, local links, complete
CLI command-tree coverage in both languages, executable safe README examples, and the absence of
private data in public text. Failure blocks release.
