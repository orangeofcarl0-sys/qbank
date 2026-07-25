# Reference projects

Use reference products for principles, not copied code, assets, or visual identity.

- Zotero: stable library hierarchy, dense item lists, and secondary attachment metadata. Reference
  only; do not copy AGPL implementation or assets.
- Visual Studio Code and Obsidian: source/editor density, restrained dark surfaces, visible focus,
  and document-first workspace behavior. Reference interaction principles only.
- PowerPoint: image-object affordances and explicit object actions. Do not copy ribbon density.
- Tauri platform guidance: preserve native window and dialog behavior and keep frontend permissions
  explicit.
- Vditor and MathJax: use the pinned, bundled dependencies already present in Studio. Do not add a
  second editor or remote renderer for visual convenience.

Qt-specific libraries such as Qlementine, qt-material, PyQt-Fluent-Widgets, QtAwesome, and superqt
are relevant only to QBank Studio Legacy. They must not be introduced into the Tauri frontend.

The maintained evaluation history is in `docs/ui/reference-evaluation.md`; its Qt entries are
Legacy context rather than modern dependency recommendations.
