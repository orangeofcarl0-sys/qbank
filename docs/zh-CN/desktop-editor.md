# qbank Studio 桌面编辑器

[English](../en/desktop-editor.md) · [中文文档](README.md)

## 范围与安装

QBank Studio 是同一 qbank 仓库中 `apps/studio/` 下的现代 Tauri presentation adapter，
可独立打包和安装，但不是另一套题库实现。Markdown 仍是权威数据，SQLite 仍可重建；题目、
taxonomy、试卷和资产写入通过 `qbank.studio_sidecar` 调用与 CLI、MCP 相同的类型化服务、
事务、校验、历史和项目锁。

```powershell
python scripts/check.py fast --scope studio
Set-Location apps\studio
npm ci
npm run tauri dev
```

正式使用应选择同一提交生成的 Windows 安装器或便携包。Studio Protocol 保持 `1.0`；
Python 包版本为 `0.3.0b1`，界面对外显示 `0.3.0-beta.1`，数据 Schema 仍为 `1.0`。

## QBank Studio Legacy

原 Qt 客户端已更名为 QBank Studio Legacy，并继续通过以下命令启动：

```powershell
pip install -e ".[desktop]"
qbank desktop
```

Legacy 只接受数据损坏、安全或严重兼容性修复。它与现代 Studio 使用相同题库格式、锁、
事务、历史和索引，不要求也不执行不可逆题库迁移。Windows 运行 Legacy 时建议使用标准
CPython，避免其他 Python 发行版附带的 Qt DLL 与 PySide6 冲突。

## 窗口与编辑模型

窗口采用两栏半布局：

- 左侧导航包含保存视图、搜索、可见筛选芯片、字段分面、包含/排除标签和题目列表；
- 中部包含 Markdown 或 TeX 源码与实时预览；
- 可折叠的右侧 Inspector 包含属性、资产、来源和历史。

紧凑工具栏显示项目健康度、试卷上下文、保存与历史、源码/预览/分栏、语法和设置。完整项目
路径可选择隐藏。主题、默认工作区、Inspector 初始状态和路径显示只影响展示，不改变题目。

打开题目不等于选择批量操作对象。选择必须显式进行，并在批量标签操作旁汇总。创建、复制、
导入和删除题目都会先 dry-run，再执行权威事务。来源类型与引用同 Markdown、待确认 taxonomy
和单一历史事件一起提交。

保存视图是可编辑快照，不是隐藏约束。全部有效条件保持可见；修改后显示已修改，并可恢复
原始快照。筛选芯片在窄导航栏内换行。若当前题目不在筛选结果中，Studio 保留编辑器并提示，
不会丢弃未保存工作。

搜索经过防抖，并在线程外读取可重建 SQLite 投影；generation token 防止旧结果覆盖新输入。
试卷上下文必须显式选择，启动时不会暗中选取第一个 YAML。

## 保存与失败行为

dirty 状态、标题标记、Inspector、源码快照和预览 generation 保持同步。若源码未保存时发起
资产操作，会显示原生“保存 / 放弃 / 取消”：保存成功才继续；放弃恢复权威快照；取消零写入。

权威提交先于索引同步。索引失败时 Markdown 与历史保持成功，索引标记为 dirty，并要求
`qbank index rebuild`。多文件权威操作失败会回滚暂存变化；补偿失败会附加报告，但不遮蔽
原始错误。

## 资产与预览

Vditor、MathJax 资源与现代 Studio 应用一起打包，可离线编辑和渲染；预览只读，Markdown
原始 HTML 继续禁用。

新图片绑定在 Markdown 中使用 `qbank-asset:<asset-id>`，在 TeX 中使用
`\qbankasset{<asset-id>}`。本地缩略图只有通过 containment 和存在性检查后才能加载。外部
HTTP/HTTPS 资源只读并警告；非法、绝对或越界路径绝不读取。按钮由真实资产能力决定，普通
PNG 不会显示可执行的 Ipe 编辑操作。

选中资产支持时，图片菜单提供八项稳定操作：

1. 使用 Ipe 编辑；
2. 从本地文件替换；
3. 从剪贴板替换；
4. 打开原始参考；
5. 重新渲染；
6. 设置首选表示；
7. 在文件管理器中显示；
8. 恢复旧版本。

拖到现有图片上请求替换；拖到符合条件的空白预览区会创建资产并插入稳定引用。Ipe 编辑使用
版本化工作副本；源变化会使派生渲染 stale，重新渲染和设为 `final` 都必须显式执行。恢复只
移动首选指针，不删除表示或历史。

## 主题与可访问性

浅色和深色主题通过语义 token 统一 Qt、CodeMirror、预览、对话框和 Inspector 卡片。原生
字体使用有效的可缩放 point size。控件提供 accessible name、完整 tooltip、可见键盘焦点和
稳定禁用状态。视觉变更按 [Studio 设计系统](../ui/design-system.md)在两种主题、100% 和 125%
缩放下验收。

## 当前边界

Studio 不内嵌聊天、OCR、在线考试系统或模型 SDK。编辑器、浏览器和文件打开均需用户直接
触发，不得由无人值守自动化启动。冻结版本边界见[已知限制](known-limitations-0.2.0.md)。
