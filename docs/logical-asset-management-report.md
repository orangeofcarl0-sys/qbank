# 逻辑资产管理验收报告

## 1. 模型

题目中的资源引用现在可以是稳定的 `asset:<asset_id>`，而不是某个特定文件名。逻辑资产具有 owner、role、status、编辑/渲染偏好、来源、备注和多个有向派生表示；表示记录 id、format、相对路径或 URL、purpose、可编辑性、派生来源、哈希与元数据。状态限定为 `raw`、`needs_redraw`、`editing`、`reviewed`、`final`、`failed`。

## 2. 存储

权威资产存放在 `assets/<question_id>/<asset_id>/`，其中 `asset.yaml` 是清单；实际表示文件和清单一同受事务与历史记录保护。`asset.schema.json` 与 `asset-package.schema.json` 由 Pydantic 模型生成，初始化也从同一包内资源生成。

## 3. 兼容性

现有 Markdown 的 `assets/...` 字符串引用仍可读、可校验和可导出。显式的 `asset:` 引用经清单解析；无法解析的逻辑引用返回稳定诊断而不会静默退回。数字化桥接仅复制 JSONL 实际引用的传统资源，并跳过 `asset:` 引用。

## 4. CLI

`qbank asset` 提供目标要求的 list、show、ingest、add、open、edit、render、replace、set-render、set-editor、finalize 与 validate，并额外提供显式兼容迁移命令 normalize。写入操作均提供 `--dry-run` 和 JSON 结果；资产包可在题目写入前预声明，以支持“先资产包、后 JSONL 题目”的原子导入流程。

## 5. Ipe

Ipe 适配器会发现 `ipe`、`ipetoipe` 与 `iperender`，缺失时返回明确错误。`asset edit` 只打开已注册且位于资产目录内的 `.ipe` 表示；`asset render` 以真实 Ipe 命令生成 PDF、SVG、PNG，并验证每个输出文件存在且非空。真实验收使用 `E:/Tool/ipe-7.2.29/bin/ipe.exe` 打开了 `ZJU841-2005-CALC-06/question-6` 的受管 Ipe 源文件，并通过 `ipetoipe.exe`、`iperender.exe` 成功生成三个渲染表示；相同内容哈希复用了既有表示 ID，随后将 `render-svg` 设为首选并重新标记为 final。

## 6. localhost 管理页

`qbank preview --serve` 只绑定 `127.0.0.1`。管理页由预览服务提供，并以会话令牌和同源请求调用实际资产服务；只能操作已登记资产，拒绝任意路径与任意命令。所有成功 mutation 仍通过题库历史记录。真实验收在端口 8871 启动服务，管理页与静态预览均返回 200，页面显示已登记的 Ipe 源表示，并通过带令牌的 localhost API 成功执行 finalize；验收后服务已关闭。

## 7. 电子工程接口

浙江大学 841 数字化项目为每个 Ipe 工作包写出 `asset-package.json`，并用 `asset:<id>` 回写其交换 JSONL。同步器把资产包交给 qbank 的 `asset ingest`，不再将 Ipe 预览文件直接复制到 qbank 的传统最终资源目录。2005 年的 `inline-tikz-1`、`answer-q5`、`question-5`、`question-6`、`question-8` 五个实际工作包均完成转换和导入；原试卷页、裁剪证据和工作包仍保留在数字化项目的 `build/ipe/`。

## 8. 试卷与导出选择

导出、预览与试卷构建通过同一资产选择服务解析逻辑资产。兼容目标格式时先采用 `preferred_render`；否则 HTML 按 SVG、PNG、JPEG、WEBP、GIF、URL 回退，PDF 按 PDF、SVG、PNG、JPEG 回退，DOCX 按 PNG、JPEG、BMP、SVG、PDF 回退，Markdown 按 SVG、PNG、JPEG、WEBP、GIF、PDF、URL 回退。`needs_redraw`、`editing` 或 `failed` 资产不会被掩盖：构建会产生稳定 warning，`assets.require_final_for_paper` 可将其升级为阻断错误。

## 9. 验证与验收

覆盖包括清单模型、legacy 兼容、资产包、输入格式、Ipe 缺失与渲染、事务、资源选择、预览服务安全、学生/答案资源隔离、数字化同步和真实 CLI 导出。qbank 共 264 项测试通过，总覆盖率 90.06%；Ruff、Pyright、7 条 import-linter 架构契约、deptry、`pip check` 与 `pip-audit` 均通过。数字化项目的 Ruff、Mypy 和全部 29 项测试通过。wheel 在源码目录外安装后可初始化包含资产 Schema、预览模板和 `$qbank` 参考资源的新题库。

真实 2005 验收题库位于 `build/ai/asset-acceptance-2005/`：5 个逻辑资产共保留 35 个表示，资产校验为 0 error、4 个预期 `needs_redraw` warning；学生 Markdown 选择 PDF 或显式首选 SVG，HTML 选择 SVG，试卷构建未产生重复 warning。隔离输出复核确认学生版没有复制 `answer-q5`，答案版则包含该表示。

## 10. 未实现的格式与编辑器

模型与资产包可保存 URL、PDF 页/裁剪、Base64/data URI、内联 TikZ、Ipe 以及其他表示；当前内建的可执行编辑/渲染适配器仅为 Ipe。TikZ 编译、PDF 裁剪提取和通用绘图编辑器仍需各自的受控适配器，不能被当作已经可编辑或可渲染的能力。
