# qbank-deliver prompts

```text
使用 $qbank-deliver 从目标题库选择两道合成题，冻结 revision、Question JSONL 和
asset_get manifest，生成学生版 PDF；不要修改题库。
```

```text
使用 $qbank-deliver 构建解析版。保留 draft 和缺失答案，但必须产生 warning 和明确的
“未提供”占位，不得补造内容。
```

```text
使用 $qbank-deliver 检查一个包含绝对路径、\input 或远程资产表示的交付工作区，确认
构建在调用 XeLaTeX 前拒绝。
```
