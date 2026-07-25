# QBank Studio design system

This document defines the current Tauri Studio presentation under `apps/studio/`. The retained Qt
client is QBank Studio Legacy; its Python theme modules and gallery remain maintenance aids for
Legacy only and are not the authority for current Studio screenshots or interaction decisions.

## Product character

QBank Studio is a compact scientific document editor rather than a dashboard. The editor and
formula preview remain visually dominant, navigation stays stable, and metadata is secondary.
The interface uses a restrained low-saturation blue accent, warm paper surfaces in light mode,
graphite chrome in dark mode, thin separators, and status colors only for status.

The stable layout is:

1. a 44 px product and repository title bar;
2. a compact navigation column for views, filters, tags, selection, and questions;
3. a dominant source/preview workspace;
4. a narrow Inspector for metadata, logical assets, and history.

At narrow widths the Inspector hides rather than compressing the editor below a useful reading
width. The native Windows title bar and platform window behavior remain unchanged.

## Visual tokens

The authoritative modern tokens are CSS custom properties on `.app-shell` in
`apps/studio/src/styles.css`.

| Role | Light direction | Dark direction |
| --- | --- | --- |
| Chrome | cool neutral | graphite |
| Editor paper | warm near-white | graphite source with light document preview |
| Raised controls | white | elevated graphite |
| Accent | low-saturation blue | lighter low-saturation blue |
| Success, warning, error | semantic use only | semantic use only |

Controls use a 28–32 px compact desktop baseline, 4–6 px radii, and a 4 px spacing rhythm. The UI
uses Segoe UI Variable/Segoe UI. Source uses a monospace stack. Borders and surface changes establish
hierarchy before shadows.

## Source authority

| Module | Responsibility |
| --- | --- |
| `apps/studio/src/styles.css` | Modern light/dark tokens, geometry, density, focus, and responsive layout |
| `apps/studio/src/studio-app.ts` | Component structure, state, labels, menus, dialogs, and orchestration |
| `apps/studio/src/icons.ts` | Central modern icon registry |
| `apps/studio/src/secure-preview.ts` | Isolated Markdown/MathJax preview and preview interaction boundary |
| `apps/studio/src/editor-buffer.ts` | Saved snapshot and dirty-state semantics |
| `apps/studio/src/advanced-management.ts` | Visible filter, tag, and saved-view presentation state |
| `apps/studio/tests/browser/visual-acceptance.spec.ts` | Deterministic theme, asset, formula, and scaling evidence |

New modern components must consume the existing semantic tokens. They must not introduce a second
theme framework, decorative dashboard cards, gradients, frameless-window behavior, or component-
local global palettes.

## Interaction and state rules

- Opening a question and selecting it for batch work remain separate actions.
- Source, split, and instant-render modes preserve one authoritative editor buffer.
- Dirty state compares current content with the last saved snapshot; returning to that snapshot
  clears the dirty indicator.
- Question, search, and preview generations reject stale asynchronous results.
- Saved views restore visible, editable filters and never add hidden duplicate constraints.
- Asset actions remain in a stable menu and derive enabled state from typed asset capabilities.
- Focus, hover, selected, disabled, loading, empty, warning, error, and success states must remain
  distinguishable without relying on color alone.
- Destructive choices and filesystem selection use Tauri's platform dialog boundary; ordinary
  in-workspace menus remain keyboard-accessible HTML controls.

## Preview and asset presentation

Vditor provides source editing while the secure preview frame renders sanitized Markdown and
offline MathJax. Raw HTML remains disabled. Dark mode intentionally retains a light preview paper
surface; this is a document-viewing decision rather than an incomplete theme transition.

Image cards behave as document objects. They show one preview, identity, preferred representation,
status, and capability menu. A local preview is shown only after repository containment and
existence checks. External and invalid resources use explicit warning or error states and are not
downloaded automatically.

## Accessibility

Every action requires a visible label or accessible name. Icon-only controls require a tooltip.
Keyboard focus must remain visible in both themes. Disabled actions stay legible and explain why
they are unavailable. Layout and text must not clip at Windows 100% or 125% scaling.

## Screenshot and review workflow

README screenshots use the production Tauri components with `FixtureRpcBridge`. The fixture exposes
only synthetic data and the stable repository identity `fixture://synthetic-bank`.

```powershell
Set-Location apps\studio
npm run test:browser -- --grep "capture deterministic light, dark, asset and formula states"
```

The generated evidence is written to `apps/studio/build/studio-prototype/screenshots/`. Before
updating public images, inspect light, dark, asset-menu, formula-menu, advanced-management, and 125%
states at full resolution. Public captures must not contain real questions, account information, or
machine-local paths.

The root `scripts/capture-ui.py` and `python -m qbank.studio_gallery` exercise QBank Studio Legacy.
They must be labeled as Legacy evidence and must not replace the Tauri captures above.
