---
schema_version: '1.0'
id: OPT-SYN-0001
title: 合成干涉条纹与相位
type: short_answer
subject: optics
chapter: wave-optics
topics:
- interference
difficulty: 2
status: reviewed
language: zh-CN
source:
  type: synthetic
  reference: public-fixture
assets:
- qbank-asset:diagram-1
- qbank-asset:ipe-figure
created_at: '2026-01-01T00:00:00Z'
updated_at: '2026-01-01T00:00:00Z'

---

## 题目

<!-- synthetic fixture: preserve this comment -->
两列等振幅波的相位差为 \(\phi\)，其合成强度满足：

\[
I = 2I_0(1 + \cos\phi)
\]

![合成波形](qbank-asset:diagram-1)

![Ipe 可编辑示意图](qbank-asset:ipe-figure)

## 选项



## 答案

当 \(\phi=2k\pi\) 时取得极大值。

## 解析

由叠加原理：

$$
\begin{aligned}
E &= E_0\cos\omega t + E_0\cos(\omega t+\phi) \\
  &= 2E_0\cos\frac{\phi}{2}\cos\left(\omega t+\frac{\phi}{2}\right).
\end{aligned}
$$

## 评分要点

- 写出相位差条件。
  - 指出整数 \(k\)。

## 审阅备注

完全由项目生成的公开合成题目。
