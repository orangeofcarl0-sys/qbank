# 内部结构重构:复杂度热点收敛(0.3.0)

> Status: implemented
>
> Target release: 0.3.0
>
> Tracking issue: 本地结构重构任务(2026-09 复杂度审计)

## 用户目标

内部维护者目标:在不改变任何用户可见行为的前提下,收敛 2026-09 复杂度审计定位的
四个结构热点,降低后续功能迭代的改动成本:

1. `apps/studio/src/studio-app.ts`(约 2,394 行、约 127 个方法的单一
   `StudioApp` 类)按功能域拆分为可独立维护的模块;
2. `src/qbank/studio_sidecar/application.py`(1,600 行)消除 pyproject 中针对
   `C901`、`PLR0912`、`PLR0915` 的 per-file 豁免,并按协议域拆分分发类;
3. 顶层 `src/qbank/operations.py`(1,076 行)重组为包结构,保持公共导入表面不变;
4. `src/qbank/application/assets.py`(1,248 行)将编辑会话与渲染辅助函数簇拆分
   为独立模块,`AssetApplicationService` 保留为门面。

题库最终用户不感知本变更;受益者是后续在该仓库上迭代的维护者、agent 与审查流程。

## 使用入口

不涉及。本变更为纯内部重构,不新增、不修改、不删除任何用户入口。

## CLI / Studio / MCP 对应关系

不涉及。CLI 命令树、Studio Protocol v1 方法集合、MCP 工具与资源清单、capability
manifest 全部保持字节级等价的公共表面。所有入口继续调用同一 `qbank.application`
服务,不复制业务规则。

## 数据与配置变化

不涉及。题库 Markdown、资产 manifest、`qbank.yaml`、taxonomy、views、papers、
`.qbank/history/`、`.qbank/index.sqlite` 及导出产物格式均不改变。Question、Asset、
Paper Schema 保持 `1.0`。

## 安全和失败行为

不改变。所有写入继续经应用服务持有项目锁并执行 dry-run、事务、历史与索引同步;
Studio 安全预览的 raw-HTML 阻断、隔离渲染与包含式资产加载语义逐字保留。拆分
`studio-app.ts` 时不触碰 `secure-preview.ts` 的对外接口;拆分 sidecar 时不改变
JSON-RPC 方法分发、stdout 协议约束与错误码。

## 兼容性与迁移

- Python:`qbank.operations` 重组为包后,`__init__` 重导出既有公共名称,0.3.0-beta
  兼容矩阵中的导入路径不变;`qbank.application.assets` 公共类表面不变。
- TypeScript:`studio-app.ts` 拆分后仍导出 `StudioApp` 作为组合根,
  `main.ts` 与 fixture 测试入口不变。
- 不需要用户迁移;不修改 `pyproject.toml` 依赖(仅删除 sidecar per-file 豁免)。
- 明确不做:`src/qbank/legacy_qt/`(约 6,141 行)在本次重构中保持冻结;它随后由
  [ADR 0009](../adr/0009-remove-qt-legacy-client.md) 彻底移除。CLI Typer 命令函数的参数
  数量(PLR0913)是 CLI 适配层惯用法,保留 per-file 豁免,仅将命令体内部逻辑收敛为
  options 对象。

## 排期与批次门禁

按测试保护强度从高到低排序,先锁定 Python 侧,最后处理单测保护最弱的 TS 侧:

| 批次 | 内容 | 通过门禁 |
| --- | --- | --- |
| B1 | sidecar `_load_studio_math` 提取为独立模块并补单测;删除 pyproject sidecar per-file 豁免 | `ruff check`、`pyright`、`mypy`、`pytest tests/studio_sidecar` |
| B2 | `operations.py` → `qbank/operations/` 包,`__init__` 重导出 | B1 门禁 + `pytest tests/test_operations*`、import-linter |
| B3 | `application/assets.py` 拆出 `asset_edits.py`、`asset_render.py` 辅助模块 | B1 门禁 + `pytest tests/test_logical_assets.py` |
| B4 | `StudioApplication` 按协议域拆分为 questions/taxonomy/views/assets/papers 分发模块 | B1 门禁 + `pytest tests/studio_sidecar protocol/tests` |
| B5 | `studio-app.ts` 按功能域拆分:app-state、taxonomy/tag 管理、批量编辑、组卷、资产操作、预览渲染;`StudioApp` 保留为组合根 | `npm run check`(eslint+tsc+vitest)、Playwright 浏览器用例、`python scripts/check.py fast --scope studio` |

每批独立可回滚(单批单提交语义),任一批失败不阻塞其余批次回滚。全部批次完成后
运行 `python scripts/check.py release` 级等价门禁(不含发布制品步骤)与
`python scripts/check_docs_sync.py`,并将本文档状态更新为 `implemented`。

## 测试与验收

- 完成标准:上述五个批次门禁全绿;`pytest --cov=qbank --cov-fail-under=90` 不降;
  import-linter 十条契约不破坏;Studio Protocol v1 契约测试(`protocol/tests`)不变;
  浏览器视觉验收用例通过,截图无用户可见差异。
- 新增测试:`_load_studio_math` 提取物的单元测试;B2/B3/B4 以既有测试为主,
  不为新包结构复制测试,仅补回归缺口。

### 实际验收结果(2026-09-25)

- B1:`tests/studio_sidecar/test_studio_math.py` 新增 12 个用例;sidecar per-file
  豁免已从 `pyproject.toml` 删除,`ruff check src` 在无豁免下全绿。附带修复:合成
  Studio fixture 的 `.qbank/studio-math.json` 被 `.gitignore` 全局规则误伤而未入库,
  导致全新克隆上两个 sidecar 测试必然失败;已入库并精确豁免。
- B2:`qbank/operations/` 包(8 个模块),公共导入表面经 `__init__` 重导出不变;
  全量 `pytest` 559 通过。
- B3:`asset_manifest.py`、`asset_render.py`、`asset_edits.py` 三个辅助模块,
  `assets.py` 由 1,248 行降至约 850 行;`tests/test_application_branch_edges.py`
  的深导入改指向新模块。
- B4:`studio_sidecar/` 拆为 `session.py`(共享会话基面)+ 5 个协议域 mixin,
  `application.py` 由 1,511 行降至约 350 行;43 个 RPC 方法分发表不变;85 个
  sidecar/protocol 测试通过。
- B5:`studio-app.ts` 由 2,394 行降至约 1,870 行;新增 `app-state.ts`、
  `ui-utils.ts`、`tag-management.ts`、`paper-management.ts`、`asset-actions.ts`;
  `npm run check`(eslint+tsc+vitest 15)与 Playwright 浏览器 36 用例全绿。附带
  修复:`bytemd-comparison` 基线用例在 Windows CRLF 检出下必然失败的行尾假设。
- 门禁:`scripts/check.py fast`(core/sidecar/studio 三个 scope)、mypy strict、
  import-linter 10 条契约、`check_docs_sync.py` 16 项检查全部通过。
- 后续:Legacy Qt 区域由 [ADR 0009](../adr/0009-remove-qt-legacy-client.md) 彻底移除;
  import-linter 契约随之收敛为 9 条。

## 当前限制

- `studio-app.ts` 拆分以行为保持为第一目标,不为视觉或交互改进留口子;后续视觉
  迭代应基于拆分后的模块边界进行,并另行遵循 `$qbank-ui-design` 流程。
- 内部模块布局(如 `qbank/operations/`)仍属 0.3.0-beta 未承诺稳定的内部 API,
  第三方不应依赖。
