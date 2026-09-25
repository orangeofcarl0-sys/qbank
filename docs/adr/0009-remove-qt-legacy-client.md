# ADR 0009：移除 QBank Studio Legacy（Qt 客户端）

- 状态：Accepted
- 日期：2026-09-25

## 上下文

`0.2.x` 时代的 Qt/PySide6 客户端在 `0.3.0` 中更名为 QBank Studio Legacy,定位为维护
回退:只接受数据丢失、安全或严重兼容修复。现代 Tauri Studio 此后承担了全部桌面编辑
交互,并在 `0.3.0-beta.2` 完成原子题库激活、资源能力分类、滚动与主题修复后,在功能与
稳定性上不再依赖 Legacy 作为回退路径。

2026-09 的复杂度审计确认 Legacy(约 6,100 行,含 `qbank.presentation` Qt 设计系统、
`qbank.studio_gallery` 入口与 `scripts/capture-ui.py` 截图脚本)是仓库中唯一不受活跃
开发约束的冻结区:它继续占据依赖豁免、测试与文档维护成本,却没有用户价值。维护者
决定彻底删除 Legacy,而不是继续双轨维护。

## 决定

1. 删除 `src/qbank/legacy_qt/`、`src/qbank/presentation/`(Qt 设计系统)、
   `src/qbank/studio_gallery.py`、`src/qbank/commands/desktop.py`、
   `scripts/capture-ui.py`、`src/qbank/resources/desktop/` 第三方声明,以及仅服务
   Legacy 的测试文件。
2. 删除 CLI 命令 `qbank desktop`。应用服务中面向交互界面的历史记录标签由
   `qbank desktop …` 更名为 `qbank studio …`;历史读取继续把旧记录中的 `desktop`
   命令显示为来源 "Studio",不迁移、不改写既有历史。
3. 删除 pip extra `desktop` 与 `studio-dev`(PySide6、QtAwesome、pytest-qt),以及
   mypy、deptry 中相应的 Qt 配置;import-linter 契约从 10 条收敛为 9 条(移除仅约束
   Qt presentation 的契约)。
4. `DesktopAssetItem`、`DesktopHistoryEntry` 等共享 DTO 与 `AssetService.desktop_items`
   保留:现代 Tauri Studio sidecar 与 MCP 继续通过这些端口消费相同的应用服务。
5. 文档、`AGENTS.md`、Skill(含打包镜像)与能力矩阵同步移除 Legacy 入口;描述
   `0.2.x` 历史版本的 `compatibility-0.2.0` 与 `known-limitations-0.2.0` 文档保持
   原样,它们记录的是已发布版本的事实。Studio Protocol 保持 `1.0`。

## 后果

### 正面

- 仓库减少约 7,300 行冻结代码与一组依赖豁免;Python 侧测试、类型检查和 lint 不再
  需要针对 Qt 的例外。
- 依赖面收敛:运行时与开发环境不再安装 PySide6/QtAwesome/pytest-qt。
- "现代 Studio 是唯一桌面客户端"成为唯一事实,文档、截图与 Skill 指引不再需要区分
  两代界面。

### 负面

- `qbank desktop` 使用者失去 Qt 回退入口;现代 Studio 成为唯一桌面界面。遇到
  Tauri Studio 无法使用时,唯一替代是 CLI 与 MCP。
- 历史记录中旧有的 `qbank desktop …` 命令标签继续存在(不迁移),新记录使用
  `qbank studio …`,来源显示保持 "Studio"。
- `pip install qbank[desktop]` / `qbank[studio-dev]` 成为无效 extra;需要 Qt 客户端的
  用户应停留在 `0.2.x` 维护线。

### 中性

- Question、Asset、Paper Schema、Markdown、taxonomy、views、papers 与
  `.qbank/index.sqlite`、历史格式均不变;本决定不涉及数据迁移。
