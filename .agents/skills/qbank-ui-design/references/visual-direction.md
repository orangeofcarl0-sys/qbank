# Visual direction

## Product character

Modern QBank Studio is a dense scientific question-document editor, not a dashboard. The Tauri
workspace follows three stable levels: compact navigation, dominant Vditor source/secure preview,
and a secondary Inspector. QBank Studio Legacy is not the visual reference for modern work.

## Palette

- Light: warm paper workspace, cool neutral chrome, graphite text.
- Dark: graphite source and chrome surfaces, with a light document-preview paper for stable formula
  and document contrast.
- Accent: one subdued blue for selection, focus, and actionable hover.
- Status: green, amber, and red only for success, warning, and error semantics.
- Maintain WCAG AA contrast for normal text and visible focus indication.

## Typography and density

- UI: Segoe UI Variable/Segoe UI at a compact desktop scale.
- Source: the Vditor monospace stack with readable leading.
- Preview: system sans plus bundled MathJax rendering.
- Controls use a 28–32 px baseline; toolbars remain compact; body text is 13–15 px.

## Geometry

- Use a 4 px base spacing rhythm and 4–6 px corner radii.
- Use 1 px separators and surface changes before shadows.
- Navigation remains compact; Inspector remains narrow and hides responsively before the editor is
  compressed below a useful width.
- Never wrap the main editor in a decorative card.

## Icons and motion

- Resolve production icons through `apps/studio/src/icons.ts`.
- Prefer familiar line icons with labels, tooltips, and accessible names.
- Limit motion to brief loading/progress feedback; honor reduced-motion preferences.
