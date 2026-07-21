# Component states

Every reusable component must define and visually review these states where
applicable:

| State | Requirement |
| --- | --- |
| Rest | Primary/secondary hierarchy remains readable. |
| Hover | Subtle surface or border change; no layout shift. |
| Focus | High-contrast focus ring independent of hover. |
| Selected | Accent-tinted surface plus readable text. |
| Disabled | Lower emphasis while retaining legibility; no pointer affordance. |
| Loading | Current object identity remains visible; actions are disabled. |
| Empty | Explain what is empty and the next useful action. |
| Error | Semantic red, concise cause, and recovery path. |
| Warning | Semantic amber without resembling selection. |
| Success | Semantic green used sparingly for confirmed outcomes. |

Review the following composites in both themes: toolbar, saved view, question
row, search and clear action, tabs/drawer, status badge, image object, native
context menu, native dialog, CodeMirror focus/selection, preview loading/error,
and Markdown/MathJax content.

