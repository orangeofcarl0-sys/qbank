---
name: qbank-ui-design
description: >
  Design, implement, or audit the qbank Studio desktop interface and its Qt,
  CodeMirror, Markdown/MathJax, navigation, drawer, dialog, or asset interactions.
  Use for every qbank Studio visual, theme, component-state, accessibility,
  screenshot, or interaction change; also use when adding Studio widgets or the
  component gallery.
---

# qbank UI design

Treat Studio as a modern scientific document editor: Zotero-like question and
attachment organization, a Markdown/TeX editor, and PowerPoint-like image-object
actions. Keep the editor/preview workspace visually dominant.

## Required workflow

1. Read [visual-direction.md](references/visual-direction.md),
   [interaction-patterns.md](references/interaction-patterns.md), and
   [component-states.md](references/component-states.md).
2. Read [reference-projects.md](references/reference-projects.md) when selecting
   dependencies, controls, icons, or global styling approaches.
3. Inspect the current Studio, its real qbank content, and both themes before
   proposing a direction.
4. State one concrete visual direction, including palette, typography, density,
   spacing, radii, and icon rules, before editing UI code.
5. Prototype new primitives in `python -m qbank.studio_gallery` before applying
   them to the production window.
6. Generate Qt Widgets, CodeMirror, and preview styles from
   `qbank.presentation.studio.design`; do not add unrelated local palettes or QSS.
7. Preserve native title bars, keyboard behavior, focus, accessibility names,
   system dialogs, and platform window behavior.
8. Launch the real application with an isolated qbank project and capture the
   required light, dark, and interaction states with `scripts/capture-ui.py`.
9. Review hierarchy, density, alignment, contrast, focus, clipping, theme
   semantics, and Qt/Web visual continuity at 100% and 125% Windows scaling.
10. Run focused interaction tests and the repository quality gates.

## Runtime preflight

On Windows, use a standard CPython 3.11+ environment for Qt work. If the active
environment inherits Anaconda Qt DLLs or `import PySide6.QtCore` fails, create an
isolated runtime before opening the gallery or Studio:

```powershell
py -3.11 -m venv build/ui-runtime/venv
build/ui-runtime/venv/Scripts/python -m pip install -e ".[desktop,dev]"
build/ui-runtime/venv/Scripts/python -c "from PySide6 import QtCore; import qtawesome"
```

Run `python -m qbank.studio_gallery` and the capture script with that same
interpreter. A structural skill validation is not a substitute for this runtime
preflight or for reviewing the resulting screenshots.

## Non-negotiable constraints

- Use real qbank questions and assets; never use lorem ipsum.
- Keep navigation compact and stable and keep metadata secondary/collapsible.
- Prefer subtle surface hierarchy and separators over large cards.
- Use restrained 4–6 px radii, one low-saturation accent, and semantic status
  colors only for status.
- Use the central icon registry; toolbar actions are icon-first with text only
  where clarity requires it.
- Avoid dashboard layouts, oversized cards, large gradients, gratuitous motion,
  frameless windows, and multiple global theme frameworks.
- Do not refactor domain models, asset models, or application services for a
  visual change. Studio continues to call application services only.
- Do not accept a visually modern result that weakens keyboard access, focus,
  native behavior, or accessibility.

## Visual acceptance

Use the repository capture script and retain baselines under `build/ui-audit/`.
At minimum verify main light/dark windows, image menus, metadata drawer, loading,
validation, and gallery light/dark states. A screenshot is evidence only after
checking it at full resolution.
