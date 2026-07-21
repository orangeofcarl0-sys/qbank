# qbank Studio design system

Studio is a dense scientific question-document editor, not a dashboard. Its native
Qt shell, CodeMirror source editor, Markdown/MathJax preview, component gallery,
menus, and dialogs derive their visual constants from
`qbank.presentation.studio.design`.

## Visual direction

- Native Windows title bar and platform window behavior.
- Compact, stable Zotero-like saved views and question list at the left.
- A collapsible, high-density tag facet sits below the question list; include/exclude
  state, counts, AND/OR mode, saved views, and field facets remain navigation controls,
  never a dashboard home page.
- Tag tables use semantic table/header tokens in both themes. Top-N matrices use
  numbered columns and heat-map headers use deliberate ellipsis plus full tooltips.
- Source and preview are the visual center; metadata remains a collapsible drawer.
- Paper-like light surfaces and graphite dark surfaces use one restrained blue
  accent. Success, warning, and error colors appear only for status.
- Controls use 4–6 px radii, 30 px height, 4/8/12/16/24/32 px spacing, thin
  separators, and icon-first editing actions.
- The narrow question-detail drawer uses stacked field labels, full-width inputs,
  embedded semantic chevrons, and borderless spin controls instead of
  platform-beveled form rows or separate arrow-button boxes.
- `Microsoft YaHei UI` is the Qt UI face. Web content uses Segoe UI with Chinese
  fallback; source uses Cascadia Mono with Consolas fallback.

## Source layout

| Module | Authority |
| --- | --- |
| `palette.py` | Light/dark semantic colors |
| `typography.py` | UI, document, and monospace families and scale |
| `metrics.py` | Density, spacing, radii, control and icon sizes |
| `tokens.py` | Immutable resolved theme snapshot |
| `icons.py` | QtAwesome semantic icon registry |
| `stylesheet.py` | Generated Qt Widgets QSS and lightweight `QProxyStyle` |
| `web_theme.py` | Generated CodeMirror/preview CSS variables and state pages |

No Studio widget should introduce a local palette, theme stylesheet, or icon name.
New semantics start as a token and are then consumed by the relevant generator.

## Interaction rules

Dirty state compares the live source and metadata with the saved snapshot, so undo
back to saved state removes the title marker and close warning. Saved views never
replace the fixed “全部题目” row; presets filter only the question list and always
show the active filter with a clear action. Question selection immediately replaces
old preview content with the selected ID and a loading state. Generation tokens
reject stale preview results, and image actions remain disabled while loading.

Image objects request a native `QMenu`; Qt owns Escape, outside-click, focus, and
keyboard dismissal. Question/view changes also close the menu. Critical decisions
use explicitly configured native `QMessageBox` instances with default buttons and
accessible names.

The preview image-drop guidance remains in document flow. It uses a full-width,
wrapping hint row and switches to a left-aligned two-line form below 520 px, so it
never overlays review notes or clips when the preview pane narrows.

## Review and maintenance

Run `python -m qbank.studio_gallery` for production component states. Use
`scripts/capture-ui.py` with an isolated real qbank
copy for screenshots. Review both themes at Windows 100% and 125% scaling; screenshots
are human/auditor evidence rather than a pixel-perfect test gate.
