---
schema_version: '1.0'
id: MATH-SYN-0002
title: 矩阵方程的分情况解
type: calculation
subject: mathematics
chapter: matrices
topics:
- linear-algebra
difficulty: 3
status: draft
language: zh-CN
source:
  type: synthetic
  reference: public-fixture
assets: []
created_at: '2026-01-02T00:00:00Z'
updated_at: '2026-01-02T00:00:00Z'

---

## 题目

设

$$
A=\begin{matrix}1&2\\3&4\end{matrix},\qquad
b=\begin{cases}1,&t\ge 0\\-1,&t<0\end{cases}.
$$

求线性方程组的形式解。

## 选项



## 答案

使用逆矩阵表示为 \(x=A^{-1}b\)。

## 解析

\[
\begin{split}
\det A &= -2,\\
A^{-1} &= -\frac12\begin{matrix}4&-2\\-3&1\end{matrix}.
\end{split}
\]

非法公式隔离样例：$\frac{1}{$，后续正文仍应显示。

## 评分要点

给出行列式与逆矩阵。

## 审阅备注

用于离线 MathJax 与局部错误测试。
