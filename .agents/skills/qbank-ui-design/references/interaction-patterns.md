# Interaction patterns

## Question navigation

- Keep “全部题目” permanently available.
- Saved views affect only the question result list and restore visible editable filters.
- Show every active filter as text and provide a keyboard-accessible clear action.
- Opening a question and selecting it for batch operations remain separate.
- On question switch, show the selected identity and loading state and reject stale generations.

## Editing and dirty state

- Compare current source and metadata with the last saved snapshot.
- Returning to the snapshot clears dirty state and save emphasis.
- Preserve standard Save, Undo, focus, selection, and keyboard behavior.
- Source, split, and instant-render modes share one authoritative buffer.

## Assets

- Images behave like document objects with a concise card and capability menu.
- Keep unsupported operations visible but disabled with an explanation.
- Close menus on Escape, outside click, question switch, view switch, and window deactivation.
- Disable conflicting asset actions while preview or repository state is loading.
- Use the platform file/dialog boundary for filesystem selection and destructive decisions.

## Theme changes

- Retheme Tauri chrome, Vditor, secure preview, Inspector, menus, and dialogs as one semantic
  operation.
- Retain the light preview paper in dark mode when required for document contrast.
- Preserve semantic roles across themes; never merely invert colors.

## Legacy boundary

Qt `QMenu`, `QMessageBox`, QSS, CodeMirror, and component-gallery instructions apply only when the
task explicitly targets QBank Studio Legacy.
