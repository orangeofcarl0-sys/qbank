# Contributing to qbank

感谢你改进 qbank。项目接受缺陷修复、文档改进、兼容性维护和经过讨论的新功能。
提交内容必须保持 Markdown 权威数据边界，并通过确定性的质量与文档同步检查。

## 开始之前

1. 使用 Python 3.11 创建隔离环境。
2. 安装开发依赖：`pip install -e ".[dev,studio-dev]"`。
3. 阅读 [维护策略](docs/maintenance-policy.md)、[功能生命周期](docs/feature-lifecycle.md)
   、[兼容性策略](docs/compatibility-policy.md)和[本地化策略](docs/localization.md)。
4. 新功能在实现前建立 `docs/features/` 功能文档或可审查的 issue 摘要。
5. 若变更架构边界、权威数据来源、事务、安全或依赖，先新增 ADR。

不要提交真实试题、答案、个人题库、本机绝对路径、凭据、私有配置、数据库、日志或
无法确认再分发权利的资产。公开示例必须为自制合成内容。

## 实现与文档

每项用户可见变更都必须评估 README、CHANGELOG、用户指南、CLI、Studio、MCP、
Codex Skill、配置、Schema、错误码、迁移说明、测试、示例、截图和已知限制。
完整检查表见 [维护策略](docs/maintenance-policy.md)。

受管用户文档必须同时更新 `docs/zh-CN/` 与 `docs/en/`。不要在同一篇正文中交替使用两种
解释性语言；命令、字段、Schema 和诊断码保留原技术标识。新增语言前必须完成受管文档覆盖，
并扩展确定性同步门禁。

功能文档应从 [统一模板](docs/features/_template.md)开始，并准确描述尚不可用的入口；
不得为了通过门禁而添加空泛或重复文档。

## 本地检查

普通改动先运行基于变更影响映射的 fast 检查：

```powershell
python scripts/check.py fast
```

Protocol、sidecar、权威写入、Vditor、MathJax、Tauri 权限或安装边界改变时运行：

```powershell
python scripts/check.py integration
```

`python scripts/check.py release` 只用于版本冻结和正式发布。变更影响映射和证据复用规则见
[单仓库开发指南](docs/monorepo-development.md)。Studio 视觉或交互变更还必须遵循仓库级
`$qbank-ui-design` Skill，并完成浅色、深色以及 100%/125% 缩放验收。发布准备必须遵循
`$oss-readiness` 和 `$release-preparation`。

统一制品入口为：

```powershell
python scripts/build.py wheel
python scripts/build.py studio
python scripts/build.py all
```

## 兼容性与版本

- `v0.2.0` 是不可移动的冻结 tag。
- 阻断性兼容修复进入 `release/0.2`，发布为 `0.2.1`。
- 新功能进入 `0.3.0`。
- 软件包版本与 Question、Asset、Paper 等数据 Schema 版本独立演进。

提交应保持范围清晰，说明用户影响、兼容性、测试结果和文档变更。除非维护者明确安排，
不要重写共享历史或重新创建已有 tag。
