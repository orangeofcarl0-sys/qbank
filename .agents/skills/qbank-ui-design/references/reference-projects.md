# Reference projects

Use these projects for principles, not copied code or a pasted visual identity.

- Zotero: borrow stable library/navigation hierarchy, dense lists, and secondary
  attachment metadata. Source is AGPL-3.0; do not copy implementation or assets.
- PyQt-Fluent-Widgets Gallery: inspect component states, icon/action clarity, and
  light/dark breadth. GPL-3.0 for non-commercial use/commercial license otherwise;
  reference only unless separately approved.
- Qlementine: inspect restrained Qt6 `QStyle` proportions and state coverage.
  MIT, but the primary project requires CMake and Qt 6.8+; use only as an isolated
  spike until a stable Python binding and packaging story are proven.
- qt-material: compare broad QSS theming and theme switching. BSD-2-Clause and
  PySide6-compatible, but its Material proportions and global stylesheet are too
  intrusive for the document-editor baseline.
- QtAwesome: preferred centralized icon-font adapter. MIT and compatible with
  PySide6 through QtPy; record bundled font licenses in notices.
- superqt: use only when a specific missing control is required. BSD-3-Clause,
  PySide6-tested; do not add it speculatively.

Authoritative evaluation and source links live in
`docs/ui/reference-evaluation.md`.

