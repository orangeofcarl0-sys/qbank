# ADR 0008：原子 Studio 题库激活与共享资源边界

- 状态：Accepted
- 日期：2026-07-27

## 上下文

现代 QBank Studio 过去通过多个请求依次打开题库、读取题目、标签和保存视图。中途失败会
让 sidecar 已切换题库而前端仍显示旧文档，或者让前端出现新旧状态混合。只读打开还缺少
明确的索引恢复入口。

Tauri Studio 和 Qt Legacy 也分别推断资源 URI、路径 containment 与可用操作。这会让同一
引用在不同 presentation adapter 中产生不同结论，并增加绝对路径或符号链接逃逸被读取的
风险。预览若对整段 HTML 做字符串替换，还可能改写非图片内容。

## 决定

1. `repository.open` 先在候选 `ProjectContext` 上创建仓储快照，读取并验证状态、题目摘要、
   标签和保存视图；全部成功后 sidecar 才替换活动题库。Tauri 前端通过一个
   `activateRepository` 边界提交完整界面状态。
2. 正常打开是只读操作。missing、dirty、stale 或 corrupt 索引返回可恢复诊断；只有用户
   明确确认后，前端才调用新增的内部 Studio Protocol 方法
   `repository.rebuildIndex`。重建和后续读取全部成功后才激活候选题库。
3. 资源 URI 分类、符号链接感知 containment、存在性、诊断和能力由共享 `AssetService`
   生成。现代 sidecar 与 Legacy 都消费相同的 `DesktopAssetItem`，presentation adapter
   不自行拼接或推断文件路径。
4. sidecar 仅为已验证且大小受限的本地图片返回 data URL，不向现代前端暴露绝对路径。
   `asset.open` 在执行前重新计算当前题目的资源清单并精确匹配 reference。
5. 预览仅重写 Markdown 生成的图片节点中与资源清单精确匹配的原始 URI，不对完整 HTML
   执行不受控字符串替换。

Studio Protocol 版本继续为 `1.0`。已有字段保留，新增字段和方法通过 capabilities 广告。
Question、Asset、Paper Schema、Markdown 和 SQLite 格式不变。

## 后果

### 正面

- 失败、取消和索引修复错误不会破坏原题库会话。
- 只读打开不会创建或修复索引，写入权限边界对用户可见。
- 现代与 Legacy 对本地、逻辑、外部和非法资源给出一致结论。
- 前端无法获得任意本地绝对路径，缩略图和打开操作都经过 sidecar 复验。
- 单一界面激活边界和 generation 检查减少旧预览、旧主题和旧 Inspector 回写。

### 代价

- `repository.open` 的首个响应更大，需要一次返回导航启动数据。
- 索引不可用时必须经过额外确认和重建步骤。
- 非逻辑本地资源在现代 Studio 中保持只读；需要可编辑生命周期时应先转为逻辑资产。

## 被拒绝的方案

### 打开题库后静默重建索引

拒绝。打开操作应保持只读，索引写入必须得到明确授权。

### 让前端直接读取本地资源

拒绝。Tauri 前端不应获得任意文件系统路径或独立实现 containment。

### 保留 Tauri 与 Qt 两套资源分类

拒绝。重复的安全边界会产生行为漂移，并使修复无法被两个 presentation adapter 共享。

## 验证

- sidecar 测试覆盖健康切换、索引缺失、显式重建及重建失败时保留旧会话。
- 资源测试覆盖合法本地图片、外部 URI、非法和越界引用、精确 reference 打开与受控缩略图。
- Playwright 覆盖失败切换、完整激活、慢请求 generation、dirty 三态、主题、滚动及本地图片
  预览。
- docs-sync、Studio fast gate、Protocol contract 和 GNU Windows 本地制品 smoke 共同验收。
