# Interaction patterns

## Question navigation

- Keep “全部题目” permanently available.
- Saved views affect only the question result list.
- Show the active filter in text and provide a keyboard-accessible clear action.
- On question switch, blank the previous preview immediately, display the new ID
  and loading state, and ignore stale render generations.

## Editing and dirty state

- Compare the current source and metadata with the last saved snapshot.
- Undoing back to that snapshot must clear dirty state and the title marker.
- Do not show a leave/close prompt when current values equal the saved snapshot.
- Preserve standard Save, Undo, Redo, focus, and selection shortcuts.

## Assets

- Images behave like document objects: hover outline, concise hint, context menu,
  double-click primary edit, and drop-to-replace.
- Prefer native `QMenu`. Escape, outside click, source focus, view switch,
  question switch, and window deactivation close the menu.
- Disable asset actions while the preview generation is loading.

## Dialogs

- Use native Qt dialogs for validation, destructive decisions, file selection,
  and unsaved changes.
- Set an explicit default button, accessible name, meaningful title, and complete
  keyboard path. Do not replace confirmations with HTML overlays.

## Theme changes

- Re-theme Qt, CodeMirror, preview HTML, menus, and dialogs as one operation.
- Preserve semantic roles across light/dark; never merely invert colors.

