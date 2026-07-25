# QBank Studio Legacy reference evaluation

Assessment date: 2026-07-21. The evaluation uses project documentation and
upstream repositories as interaction references only; no external source or
visual assets are copied into qbank.

This record predates the Tauri Studio becoming the default desktop entry. Its
Qt/PySide6 dependency decisions now apply only to QBank Studio Legacy. The
current Tauri design authority is [design-system.md](design-system.md).

| Project | Useful reference | Fit for qbank | License | Qt/PySide6 constraints | Intrusiveness | Production dependency |
| --- | --- | --- | --- | --- | --- | --- |
| [Zotero](https://www.zotero.org/support/licensing) | Stable library tree, dense item list, attachment/source organization, secondary metadata pane | High as an information-architecture reference | AGPL-3.0 source | Not a Qt/PySide6 toolkit | Copying implementation would be highly invasive | No; reference only |
| [PyQt-Fluent-Widgets Gallery](https://pyqt-fluent-widgets.readthedocs.io/en/stable/license.html) | Comprehensive control states, icon-led actions, light/dark gallery | Medium; useful state coverage but Fluent window patterns are too application-shell-heavy | GPL-3.0 for non-commercial use, commercial license otherwise | Separate PySide6 branch/package; package namespace conflicts are documented upstream | High; replaces many native widgets and often pairs with frameless-window behavior | No; license and shell intrusion make it reference-only without explicit approval |
| [Qlementine](https://github.com/oclero/qlementine) | Restrained Qt-native proportions, polished `QStyle`, broad widget states | Medium-high visually | MIT | Primary project requires Qt 6.8+ and CMake 3.21+; C++ is 98% of upstream. Python bindings observed in 2026 remain pre-release | High packaging/build intrusion for this pure-Python wheel | No; retain as reference/minimal spike until binding and wheel maturity are proven |
| [qt-material](https://github.com/UN-GCPDS/qt-material) | Fast global light/dark comparison, density controls, menu/dialog consistency checks | Medium-low; Material control geometry competes with a dense document editor | BSD-2-Clause | Explicit PySide6 support | Medium-high global stylesheet ownership; QWebEngine still needs separate styling | No; use only as an isolated comparison spike |
| [QtAwesome](https://github.com/spyder-ide/qtawesome) | Central icon registry and consistent toolbar/menu icons | High | MIT package; bundled icon fonts retain their own OFL/CC licenses | Supports PyQt/PySide through QtPy; Windows wheels are established | Low and localized | Yes, in the desktop extra |
| [superqt](https://pypi.org/project/superqt/) | Focused missing Qt widgets and utilities | Conditional | BSD-3-Clause | Tested with PySide6 and Python 3.10+ | Low when one widget is selected, unnecessary otherwise | No current need; do not add speculatively |

## Dependency spikes and decision

### A — native PySide6 baseline

Use native Qt Widgets and dialogs, centralized immutable design tokens, a light
`QProxyStyle`/generated QSS layer, generated CodeMirror/preview CSS, and QtAwesome
icons. It preserves platform behavior and the current application-service boundary
while keeping theme ownership in one small qbank package.

### B — qt-material comparison

The gallery comparison records that qt-material supplies broad widget styling and
runtime theme switching, but its Material geometry is too spacious for the desired
scientific-editor density. Applying a global stylesheet also leaves CodeMirror and
QWebEngine content as a separate theming responsibility. It is not installed in the
production environment.

### C — Qlementine feasibility

Upstream is a Qt 6.8+/CMake C++ `QStyle`. A PySide6 binding exists only as a
pre-release candidate in the evaluated ecosystem. That adds binary-wheel and
Windows packaging uncertainty without replacing the need for web-surface tokens.
No binding is introduced into the production application.

## Legacy decision

Select A. It has the lowest licensing, packaging, startup, accessibility, and
maintenance risk while meeting the required visual consistency. Add QtAwesome only;
defer superqt, qt-material, Qlementine, and QFluentWidgets. This decision does
not authorize those dependencies in the modern Tauri frontend.
