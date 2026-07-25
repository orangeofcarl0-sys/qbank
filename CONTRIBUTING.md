# Contributing to qbank

感谢你愿意改进 qbank。这里欢迎代码、文档、测试、界面建议、可复现问题，以及能帮助 coding
agent 更好完成题库工作的真实流程反馈。小修正可以直接提交；范围较大的功能先开 issue，
确认目标和数据边界即可。

qbank 是一个 AI-first coding 项目。仓库中的实现与文档通过 coding agent 生成或修改，但
贡献者和维护者仍对提交内容、许可证、测试结果与发布决定负责。无需附上完整聊天记录；
请在提交说明中写清楚问题、用户影响、主要取舍和验证结果。

## 开始工作

使用 Python 3.11 创建隔离环境并安装开发依赖：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,studio-dev]"
```

普通缺陷、文案或测试改进可以直接开始。新增功能请先建立一个简短 issue 或
`docs/features/` 功能文档；只有在改变架构边界、权威数据、事务、安全或依赖时才需要 ADR。
相关背景见[维护策略](docs/maintenance-policy.md)和
[功能生命周期](docs/feature-lifecycle.md)。

## 与 coding agent 协作

- 给 agent 明确目标、受影响入口、允许写入的范围和验收方式。
- 不要把真实试题、答案、个人题库、凭据、私有配置或本机路径放进 prompt、fixture 或提交。
- 公开示例使用自制合成内容；第三方图片、字体和数据必须先确认再分发权利。
- 对题库写入先 dry-run，再检查差异并验证结果。
- Agent 生成的结果应像其他贡献一样经过审阅；“由 AI 生成”既不是拒绝贡献的理由，也不是
  跳过验证的理由。

## 文档与兼容性

用户可见变化应更新实际受影响的 README、CHANGELOG、用户指南、CLI、Studio、MCP、Skill、
配置、Schema、示例或限制说明，不需要为未受影响的部分制造占位文字。受管用户文档在
`docs/zh-CN/` 与 `docs/en/` 成对维护。

`0.1.x` 已不再支持。`0.2.x` 只接受安全、数据损坏和阻断性兼容修复，其中 Qt 桌面端作为
QBank Studio Legacy 维护；新功能进入当前 `0.3.x` 开发线。已发布 tag 不会移动，修复通过
新版本提供。软件版本与 Question、Asset、Paper 等数据 Schema 版本独立演进。

## 提交前检查

一般改动运行：

```powershell
python scripts/check.py fast
```

Protocol、sidecar、权威写入、编辑器、Tauri 权限或安装边界发生变化时，再运行：

```powershell
python scripts/check.py integration
```

`python scripts/check.py release` 只用于版本冻结和发布。Studio 视觉或交互变更还应遵循
仓库级 `$qbank-ui-design` Skill，并检查浅色、深色和常用缩放。统一构建入口为
`python scripts/build.py wheel|studio|all`。

提交说明保持简洁即可：说明改了什么、为什么改、如何验证，以及是否影响兼容性或文档。
