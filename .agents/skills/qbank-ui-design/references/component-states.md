# Component states

Every reusable modern Studio component defines and visually reviews these states where applicable:

| State | Requirement |
| --- | --- |
| Rest | Primary and secondary hierarchy remains readable. |
| Hover | Subtle surface or border change without layout shift. |
| Focus | High-contrast focus ring independent of hover. |
| Selected | Accent-tinted surface plus readable text or a second non-color cue. |
| Disabled | Lower emphasis while retaining legibility and an unavailable explanation. |
| Loading | Current object identity remains visible and conflicting actions are disabled. |
| Empty | Explain what is empty and the next useful action. |
| Error | Semantic red, concise cause, and recovery path. |
| Warning | Semantic amber without resembling selection. |
| Success | Semantic green used only for confirmed outcomes. |

Review title bar, navigation, saved views, filter chips, question rows, batch selection, document
toolbar, Vditor focus and selection, secure preview, Inspector forms, asset cards and menu, formula
menu, platform dialogs, toasts, and loading/error states in both themes.

Qt widget composites are reviewed separately only for explicitly scoped QBank Studio Legacy work.
