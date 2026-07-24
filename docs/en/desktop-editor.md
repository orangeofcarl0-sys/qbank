# qbank Studio desktop editor

[简体中文](../zh-CN/desktop-editor.md) · [English documentation](README.md)

## Scope and installation

Studio is the optional local Qt presentation for the existing qbank application, not a second
question-bank implementation. Markdown remains authoritative, SQLite remains rebuildable, and
question, taxonomy, paper, and asset mutations use the same typed services, transactions,
validation, history, and project lock as the CLI.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[desktop]"
qbank desktop
```

Standard CPython is recommended on Windows because Qt DLLs bundled by another Python distribution
can conflict with PySide6.

## Window and editing model

The window uses a two-and-a-half-column layout:

- the left navigation contains saved views, search, visible filter chips, field facets, include/
  exclude tags, and the question list;
- the center contains Markdown or TeX source and live preview;
- the collapsible right Inspector contains properties, assets, source provenance, and history.

The compact toolbar shows project health, paper context, save/history actions, source/preview/split
mode, syntax, and settings. Displaying the full project path is optional. Presentation settings
cover theme, initial workspace mode, Inspector visibility, and path visibility; they do not alter
question data.

Opening a question does not select it for bulk operations. Selection is explicit and summarized
beside bulk tag actions. Creating, copying, importing, and deleting questions always performs a
dry-run before the authoritative transaction. Source type and reference are committed with Markdown,
pending taxonomy entries, and one history event.

Saved views are editable snapshots, not hidden constraints. Every active filter remains visible;
changes mark the view as modified and the original snapshot can be restored. Filter chips wrap in
the compact navigation column. If the open question is outside the current result set, Studio keeps
the editor open and reports that state rather than discarding unsaved work.

Search is debounced and reads the rebuildable SQLite projection off the UI thread. Generation tokens
prevent older results from replacing newer input. Paper context is explicit: Studio never silently
chooses the first paper definition at startup.

## Save and failure behavior

Dirty state, title indicator, Inspector values, source snapshot, and preview generation are kept in
sync. Asset operations encountered while source is dirty present a native Save / Discard / Cancel
decision. Save must succeed before the operation continues; Discard restores the authoritative
snapshot; Cancel performs no write.

Authority commits happen before index synchronization. An index failure leaves Markdown and history
committed, marks the index dirty, and requires `qbank index rebuild`. Failed multi-file authoritative
operations roll back their staged changes; compensation failures are reported without hiding the
original error.

## Assets and preview

CodeMirror 6 is bundled in the wheel and works offline. MathJax follows the existing CDN policy.
Preview is read-only and raw HTML in Markdown remains disabled.

New image bindings use `qbank-asset:<asset-id>` in Markdown or `\qbankasset{<asset-id>}` in TeX.
Local thumbnails open only after containment and existence checks. External HTTP/HTTPS resources are
read-only and warned; invalid, absolute, or escaping paths are never loaded. Available buttons derive
from real asset capabilities, so ordinary PNG files do not advertise Ipe editing.

The image context menu provides eight stable actions when the selected asset supports them:

1. edit with Ipe;
2. replace from a local file;
3. replace from the clipboard;
4. open the original reference;
5. rerender;
6. set the preferred representation;
7. show in the file manager;
8. restore a previous version.

Dropping on an image requests replacement; dropping in an eligible blank preview area creates an
asset and inserts its stable reference. Ipe editing uses a versioned working copy. A changed source
makes derived renders stale; rerendering and promotion to `final` are always explicit. Restore moves
preference pointers and does not delete representations or history.

## Themes and accessibility

Light and dark themes share semantic design tokens across Qt, CodeMirror, preview, dialogs, and
Inspector cards. Native fonts use valid scalable point sizes. Controls provide accessible names,
full tooltips, visible keyboard focus, and stable disabled states. Visual changes are accepted at
100% and 125% scaling in both themes according to the [Studio design system](../ui/design-system.md).

## Current boundaries

Studio does not embed chat, OCR, an online exam system, or a model SDK. Interactive editor, browser,
and file-opening actions require the user's direct action and must not be launched by unattended
automation. See [known limitations](known-limitations-0.2.0.md) for frozen-release constraints.
