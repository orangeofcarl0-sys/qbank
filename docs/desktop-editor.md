# qbank desktop editor

## Scope

The optional desktop extra provides a local Qt Widgets editor for the existing
qbank application. It is a presentation adapter, not a separate question-bank
implementation: Markdown remains authoritative, SQLite remains rebuildable,
and all question and asset mutations pass through the same typed services,
transactions, validation, and history used by the CLI.

Install and launch it with:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[desktop]"
qbank desktop
```

Standard CPython is recommended on Windows because an Anaconda installation's
bundled Qt DLLs can conflict with PySide6.

## Interaction model

The window has a two-and-a-half-column layout:

- saved query views, removable filter chips, question list, field facets, and a
  collapsible include/exclude tag selector on the left;
- Markdown/TeX source and live preview in the center;
- a collapsible basic/assets/source/history drawer on the right.

Unknown Inspector topics are normalized to pending slugs. If registered names or
aliases look similar, Studio asks for confirmation before retaining the new chip.
Saved views resolve retained taxonomy aliases after a global rename or merge.
They are editable snapshots rather than hidden base constraints: every active
condition remains visible, modifications are marked, and the original snapshot
can be restored from the view menu. Filter chips wrap inside the compact
navigation column instead of being clipped.

The single compact toolbar names the active bank and exposes validation and
index state through accessible status symbols and complete tooltips. The full
project path is optional. The Studio settings button opens presentation-only
preferences for theme, default source/preview/split mode, detail-drawer startup
visibility, and project-path visibility. Opening a question does not select it
for bulk operations; selection is explicit and summarized next to the bulk tag
actions. Question create, copy, JSON/JSONL import, and delete commands always
dry-run before their authoritative transaction. Source type and reference are
editable fields and are saved in the same transaction as Markdown, pending
taxonomy entries, and one unified history event.

Paper context is explicit. Studio does not silently choose the first YAML file at
startup. The paper menu selects or creates a definition before add, validate,
build, or export actions become meaningful. Search is debounced and evaluated
against the rebuildable SQLite projection off the UI thread; generation tokens
prevent an older result from replacing a newer query.

Save, undo, redo, validate, source/preview/split, and Markdown/TeX controls stay
close to the editor. CodeMirror 6 is bundled in the wheel and does not need a
network connection. MathJax continues to use the existing CDN policy.

Images use stable `qbank-asset:<asset-id>` bindings. TeX source can use
`\qbankasset{<asset-id>}`. Legacy `asset:` and managed path references remain
readable; preview is read-only, and a legacy path is materialized only when its
first asset mutation is requested.

The preview exposes exactly eight context actions:

1. edit with Ipe;
2. replace with a local file;
3. replace from the clipboard;
4. open the original reference;
5. rerender;
6. set the preferred representation;
7. show in the file manager;
8. restore the previous version.

Double-click opens the preferred editor. Dropping a file over an existing image
replaces it; dropping over the blank preview creates an asset and inserts its
stable reference.

Ipe editing creates a versioned working copy and preserves the original. When
the saved hash changes, derived renders become stale. The user must explicitly
rerender, and qbank never changes the asset to `final` automatically. Restore
changes preference pointers without deleting any representation or history.

## 2005 acceptance fixture

The real Zhejiang University 841 2005 fixture was copied to
`build/ai/desktop-acceptance-2005` for non-destructive acceptance testing.
The run verified:

- source text and a TeX formula could be saved, reopened, and previewed;
- the real question-6 diagram was bound to its logical asset and the eight-item
  context menu opened;
- Ipe opened a versioned working copy, a saved change was reconciled, and real
  PDF/SVG/PNG rerendering succeeded;
- a question-8 image could be replaced locally and restored without deleting
  versions;
- the four-question paper validated and student/answer Markdown builds
  succeeded;
- the student build excluded the answer-only question-5 asset, while the answer
  build included it.

The visual acceptance capture is
`build/ai/desktop-acceptance-2005.png`.
