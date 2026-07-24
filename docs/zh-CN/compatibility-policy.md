# 兼容性策略

[English](../en/compatibility-policy.md) · [中文文档](README.md)

qbank 将已记录的 CLI 和数据格式视为兼容性敏感接口。`v0.2.0` tag 是不可变发布基线，永远
不得移动或重建。

## 发布线与独立版本

- 0.2.x 的阻断性兼容或安全修复在 `release/0.2` 开发，并发布为 `0.2.1` 或后续 patch。
- 新功能进入 `0.3.0`。
- Python 软件包版本与 Question、Asset、Paper、taxonomy 和 view Schema 版本独立。软件发布
  不代表 Schema 变化；Schema 变化必须独立定版和记录。

## 冻结版本与后续文档

`v0.2.0` tag 及其 wheel、sdist、checksums 和 provenance 永远对应原冻结提交。tag 后的文档
维护提交属于候选 `main` 历史，不改变制品身份。GitHub 自动源码归档来自所选 tag，因此不含
后续文档。

## 受保护接口

下列内容变化必须进行兼容性审查和回归测试：

- 命令、选项名称、默认值和退出码；
- JSON 字段、嵌套、可选字段输出和诊断码；
- question、paper、patch、asset 和 asset-package JSON Schema；
- 逻辑资产 URI 含义和旧资产路径读取；
- 可接受的 Markdown front matter 和有序正文段；
- 已记录或被测试导入的 Python 兼容适配器；
- 项目布局与初始化资源。

只有现有消费者仍能解析时才可新增字段。删除或改变字段、命令、选项、枚举、诊断码或
Markdown 含义，必须有明确兼容性决定和 CHANGELOG 记录。

配置或 Schema 变化还必须提供更新后的兼容性/迁移文档、说明数据影响的功能文档、读取现有
受支持数据的测试，以及迁移步骤或“无需迁移”的明确结论。

## 规范往返

时间规范化后，有效题目必须保持：

```text
Question -> exchange JSON -> Question -> Markdown -> Question -> exchange JSON
```

两份 exchange JSON 必须相等。JSON Schema 直接由 Pydantic 模型生成，仓库根部 Schema 必须
与生成结果逐字节一致。

## 失败兼容性

兼容性包括失败行为。无效筛选、损坏源文件、索引不可用、输出冲突和无效交换数据应保留已
记录的退出类别和稳定诊断码。JSON 模式保持可解析，不把人类 warning 混入 stdout。

## 弃用与文档

发布前，内部 API 可迁移到轻量、经过测试的兼容适配器之后。面向用户的破坏性变化必须提供
ADR、CHANGELOG、更新后的 Schema 与示例，以及专门迁移说明或明确的“无需迁移”结论。

文档同步门禁是发布准备的一部分。缺少用户文档、翻译对等、迁移指引或 CHANGELOG 时，即使
运行时测试通过也不得发布。
