# Visual direction

## Product character

Studio is a dense scientific question-document editor, not a dashboard. The
workspace follows three stable levels: compact question navigation, dominant
source/preview editing, and a collapsible detail drawer.

## Palette

- Light: warm paper-like workspace, cool neutral chrome, graphite text.
- Dark: graphite surfaces rather than pure black, with slightly elevated editor
  and drawer surfaces.
- Accent: one subdued blue used for selection, focus, and actionable hover.
- Status: green, amber, and red only for success, warning, and error semantics.
- Maintain WCAG AA contrast for normal text and visible focus indication.

## Typography and density

- UI: native system sans (`Segoe UI` on Windows) at a compact desktop scale.
- Source: `Cascadia Code`, then `JetBrains Mono`/`Consolas`, with readable leading.
- Preview: system sans with compact scientific-document headings.
- Controls use a 30–32 px baseline; toolbars remain compact; body text is 13–15 px.

## Geometry

- Use a 4 px base spacing rhythm and 4–6 px corner radii.
- Use 1 px separators and surface changes before shadows.
- Navigation remains about 248 px; drawer about 300 px; workspace receives the
  remaining width.
- Never wrap the main editor in a decorative card.

## Icons and motion

- Resolve every production icon through the Studio icon registry.
- Prefer familiar line icons and retain text/tooltips/accessibility names.
- Limit motion to brief loading/progress feedback. Never animate layout for
  decoration.

