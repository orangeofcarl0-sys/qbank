---
schema_version: '1.0'
id: TEST-ROUNDTRIP-0001
title: Round-trip 合成样例
type: short_answer
subject: testing
chapter: editor
topics:
- roundtrip
difficulty: 1
status: draft
language: zh-CN
source:
  type: synthetic
assets:
- qbank-asset:diagram-1
---

## 题目

<!-- comment must survive -->
自定义宏：$\qop(x)$。
中文与行内公式 \(a+b\) 及美元公式 $c+d$。

![图形](qbank-asset:diagram-1)

1. 一级列表
   - 缩进子项

$$
\begin{aligned}
x &= 1 \\
y &= 2
\end{aligned}
$$

## 选项



## 答案

答案。

## 解析

\[
\begin{cases}
x=1, & t\ge 0\\
x=-1, & t<0
\end{cases}
\]

\[
\begin{matrix}
1 & 0 \\
0 & 1
\end{matrix}
\]

\[
\begin{split}
f(x) &= x^2 + 2x + 1 \\
     &= (x+1)^2
\end{split}
\]

## 评分要点

要点。

## 审阅备注

备注。非法公式局部错误样例：$\frac{1}{$，其后文本必须继续显示。
