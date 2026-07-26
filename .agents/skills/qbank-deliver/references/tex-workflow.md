# Controlled TeX workflow

The agent writes only `content.tex`. The builder supplies the document class,
metadata, asset paths, edition switches, and document wrapper.

Use these structures:

```tex
\begin{qbankquestion}{DEMO-MATH-0001}{函数极值}{10}{reviewed}
求函数 \(f(x)=x^2\) 的最小值。
\begin{qbankchoices2}
  \item \(0\)
  \item \(1\)
\end{qbankchoices2}
\qbankanswer{DEMO-MATH-0001}{\(0\)}
\qbanksolution{DEMO-MATH-0001}{由 \(x^2\geq 0\)，最小值为 \(0\)。}
\qbankrubric{DEMO-MATH-0001}{写出非负性并得到结论。}
\end{qbankquestion}
```

For a logical asset:

```tex
\qbankasset[0.72\linewidth]{DEMO-FIG-0001}{figure-1}
```

Allowed qbank structures are:

- `qbankquestion` with ID, short title, score, and status;
- `qbankchoices2` and `qbankchoices4`, containing ordinary `\item` entries;
- `\qbankasset[width]{question-id}{asset-id}`;
- `\qbankanswer{id}{...}`, `\qbanksolution{id}{...}`, and
  `\qbankrubric{id}{...}`.

Ordinary TeX text and mathematics are permitted inside those structures. Do not
emit `\documentclass`, document boundaries, `\input`, `\include`,
`\includegraphics`, file-writing commands, shell escape, package loading, macro
redefinition, TeX `^^` character encoding, internal `\@...` commands, or absolute
paths. Do not emit TeX comments. The builder accepts only its explicit qbank and
common-math command allowlist, rejects every unknown control sequence, and always
disables shell escape.

Every selected question appears exactly once and in selection order. Reuse the same
`content.tex` for all editions: the fixed template controls which answer sections
are visible.
