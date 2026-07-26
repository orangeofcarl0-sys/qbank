\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{qbankexam}[2026/07/26 qbank Chinese exam template v1]
\LoadClass[UTF8,12pt,a4paper]{ctexart}

\RequirePackage{amsmath,amssymb}
\RequirePackage{enumitem}
\RequirePackage{fancyhdr}
\RequirePackage{geometry}
\RequirePackage{graphicx}
\RequirePackage{multicol}
\RequirePackage{xcolor}
\RequirePackage{xparse}

\geometry{left=24mm,right=24mm,top=24mm,bottom=25mm}
\definecolor{qbankblue}{HTML}{365F7D}
\definecolor{qbankmuted}{HTML}{64748B}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\qbanksubject}
\fancyhead[R]{\small\qbanktitle}
\fancyfoot[C]{\thepage}
\setlength{\headheight}{15pt}
\setlist{nosep,leftmargin=2em}

\newcommand{\qbanktitle}{题目文档}
\newcommand{\qbanksubject}{}
\newcommand{\qbankdate}{}
\newcommand{\qbankduration}{}
\newcommand{\qbankvariant}{student}
\newcommand{\qbanksettitle}[1]{\renewcommand{\qbanktitle}{#1}}
\newcommand{\qbanksetsubject}[1]{\renewcommand{\qbanksubject}{#1}}
\newcommand{\qbanksetdate}[1]{\renewcommand{\qbankdate}{#1}}
\newcommand{\qbanksetduration}[1]{\renewcommand{\qbankduration}{#1}}
\newcommand{\qbanksetvariant}[1]{\renewcommand{\qbankvariant}{#1}}

\newcommand{\qbankmaketitle}{
  \begin{center}
    {\LARGE\bfseries \qbanktitle\par}
    \vspace{0.6em}
    {\qbanksubject\quad \qbankdate\quad \qbankduration\par}
  \end{center}
  \vspace{0.8em}
  \hrule
  \vspace{1.2em}
}

\newcounter{qbankquestion}
\NewDocumentEnvironment{qbankquestion}{mmmm}{
  \refstepcounter{qbankquestion}
  \par\medskip\noindent
  \textbf{\theqbankquestion.\ #2}\hfill\textbf{#3 分}
  \def\qbankstatus{#4}
  \def\qbankdraft{draft}
  \ifx\qbankstatus\qbankdraft
    \quad{\small\color{qbankmuted}[待核]}
  \fi
  \par\smallskip
}{
  \par\medskip
}

\NewDocumentEnvironment{qbankchoices2}{}{
  \begin{multicols}{2}
  \begin{enumerate}[label=\Alph*.,itemsep=0.25em]
}{
  \end{enumerate}
  \end{multicols}
}
\NewDocumentEnvironment{qbankchoices4}{}{
  \begin{multicols}{4}
  \begin{enumerate}[label=\Alph*.,itemsep=0.2em]
}{
  \end{enumerate}
  \end{multicols}
}

\newcommand{\qbankmissing}{\textcolor{qbankmuted}{未提供}}
\newcommand{\qbankanswer}[2]{
  \def\qbankstudent{student}
  \ifx\qbankvariant\qbankstudent\else
    \par\smallskip\noindent\textbf{答案：}#2
  \fi
}
\newcommand{\qbanksolution}[2]{
  \def\qbanksolutionvariant{solution}
  \ifx\qbankvariant\qbanksolutionvariant
    \par\smallskip\noindent\textbf{解析：}#2
  \fi
}
\newcommand{\qbankrubric}[2]{
  \def\qbanksolutionvariant{solution}
  \ifx\qbankvariant\qbanksolutionvariant
    \par\smallskip\noindent\textbf{评分要点：}#2
  \fi
}
\NewDocumentCommand{\qbankasset}{O{0.78\linewidth}mm}{
  \par\smallskip\begin{center}
    \expandafter\includegraphics\expandafter[width=#1]
      {\csname qbankasset@#2@#3\endcsname}
  \end{center}\smallskip
}
