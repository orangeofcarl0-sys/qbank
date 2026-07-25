# QBank Studio desktop editor

[简体中文](../zh-CN/desktop-editor.md) · [English documentation](README.md)

## Product boundary

QBank Studio is qbank's default desktop entry and the modern Tauri presentation adapter under
`apps/studio/`. It communicates with the local `qbank.studio_sidecar` through Studio Protocol
`1.0` and reuses the application services, project lock, transactions, validation, history, and
index policy used by the CLI and MCP. Question Markdown and logical assets remain authoritative;
Studio does not maintain a second repository format.

The current pre-release UI is `0.3.0-beta.1`, the Python package is `0.3.0b1`, and the Question,
Asset, and Paper Schemas are `1.0`. The Windows installer is unsigned. Verify the Release SHA-256
values as described in the [installation and upgrade guide](installation.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/readme/studio-main-dark.png">
  <img src="../assets/readme/studio-main-light.png" alt="Modern Tauri QBank Studio with navigation, Markdown and formula preview, and the Inspector" width="1480">
</picture>

The image uses a public synthetic fixture and contains no examination material, user data, or
machine-local absolute path.

## Workspace structure

Studio uses a stable three-region document-editing layout:

- the title bar identifies the product and current repository, reports repository health, and
  switches theme;
- the left navigation opens repositories and provides create, copy, import, delete, saved views,
  search, filters, tags, and the question list;
- the central workspace contains document actions, identity and validation state, plus source,
  split, and instant-render editing modes;
- the right Inspector edits core properties and presents logical assets and recent history. It
  automatically hides at narrow window widths to preserve the editor workspace.

The repository path confirms the active working location and is visually truncated when space is
limited. Documentation captures use `fixture://synthetic-bank` rather than a maintainer or user
directory.

Opening a question and selecting questions for batch operations are separate states. Opening does
not implicitly select the question. If filters exclude the open question, Studio keeps its editor
available so unsaved work is not interrupted.

## Editing, validation, and save

Markdown/TeX source is the authoritative editor buffer. Vditor, MathJax, and preview resources ship
with the application, so source, split, and instant-render modes work offline. Raw HTML remains
disabled. The preview runs in an isolated frame and never writes back to Markdown.

Dirty state, save availability, source snapshot, Inspector values, and preview generation stay
synchronized. Save and metadata updates ask the sidecar to prepare a dry-run before committing the
same authoritative transaction. Validation and index synchronization follow a successful commit.
An index failure does not roll back committed Markdown and history; it marks the index dirty and
requires:

```powershell
qbank index rebuild --format json
```

Failed multi-file authoritative operations roll back staged changes. Compensation failures are
reported as additional diagnostics without hiding the original commit error.

## Search, filters, and saved views

Search reads the rebuildable SQLite index and uses generation tokens so older results cannot
replace newer input. A saved view is an editable snapshot of visible filters; it does not apply a
second set of hidden controller constraints. Field facets, included or excluded tags, AND/OR mode,
and removable chips fully describe the current result. Clearing filters restores “All questions”
in one refresh.

Special views such as redraw-needed and current-paper define only a member scope and can still be
combined with visible filters. Filter chips wrap inside the compact navigation column and remain
individually removable.

## Logical assets

An asset card presents the preferred representation, status, preview, and a capability menu. The
menu keeps the following actions in a stable order and enables them only when the selected asset
supports the operation:

1. open original;
2. edit with Ipe;
3. detect changes and rerender;
4. replace from a local file;
5. replace from the clipboard;
6. rerender;
7. reveal in the file manager.

![Logical-asset capability menu in dark mode](../assets/readme/studio-assets-dark.png)

A local resource loads only when it exists inside the configured repository asset boundary.
HTTP/HTTPS resources remain read-only and generate warnings. Absolute, invalid, and escaping URIs
are never read. Ipe editing uses a versioned working copy; a changed source makes derived renders
stale and rerendering remains explicit.

Dropping onto an existing image requests replacement. Dropping in an eligible editor region creates
a logical asset and inserts its stable reference. If source is dirty, an asset operation requires
Save, Discard, or Cancel; only a successful save or an explicit discard allows the operation to
continue.

## Themes and accessibility

One set of semantic CSS tokens drives the Tauri navigation, Vditor, isolated preview, Inspector,
menus, statuses, and dialogs in both themes. Dark mode retains a light paper surface for document
preview so formulas and document content preserve stable contrast.

Buttons, menus, and fields provide accessible names, keyboard focus, tooltips, and explicit disabled
states. Visual acceptance uses the current Tauri components at 100% and 125% scaling in both themes.
Qt Legacy captures must not be used as evidence for the current Studio README or interaction model.
See the [Studio design system](../ui/design-system.md).

## QBank Studio Legacy

`qbank desktop` starts the retained Qt client, QBank Studio Legacy:

```powershell
pip install "qbank[desktop]"
qbank desktop
```

Legacy reads the same repository format but accepts only data-loss, security, or severe
compatibility fixes. It is not the default desktop entry and does not represent the modern Studio
interface or interaction model. No repository migration is required between the clients.

## Development and acceptance

```powershell
python scripts/check.py fast --scope studio
Set-Location apps\studio
npm ci
npm run tauri dev
npm run test:browser
```

README captures are generated deterministically from production components and a public synthetic
fixture in browser acceptance. The packaged application still receives a minimal startup and
repository-open smoke. Studio does not embed chat, OCR, an online exam system, or a model SDK. See
the [0.3.0-beta.1 known limitations](known-limitations-0.3.0-beta.1.md).
