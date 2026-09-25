---
name: qbank-ui-design
description: >
  Design, implement, document, or audit the modern Tauri QBank Studio interface
  and its Vditor, Markdown/MathJax preview, navigation, Inspector, dialogs,
  assets, themes, screenshots, and accessibility. The Qt Legacy client was
  removed in 0.3.0.
---

# qbank UI design

Treat the current Studio as a compact scientific document editor: stable library-like navigation,
a dominant Markdown/TeX source and preview workspace, and a secondary Inspector. The modern product
lives under `apps/studio/` and is the only desktop client.

## Required workflow

1. Read [visual-direction.md](references/visual-direction.md),
   [interaction-patterns.md](references/interaction-patterns.md), and
   [component-states.md](references/component-states.md).
2. Read [reference-projects.md](references/reference-projects.md) before selecting dependencies,
   controls, icons, or global styling approaches.
3. All Studio work targets the modern Tauri Studio under `apps/studio/`.
4. Inspect the current production components, public synthetic fixture, both themes, and the
   affected 100%/125% states before editing.
5. State one concrete visual direction covering palette, typography, density, spacing, radii,
   responsive behavior, and icon rules.
6. Build modern components from `apps/studio/src/styles.css`, `studio-app.ts`, the central icon
   registry, and the secure preview boundary. Do not copy Python Qt styling into Tauri.
7. Preserve native Tauri title-bar behavior, platform dialogs, keyboard behavior, focus,
   accessibility names, and filesystem authorization.
8. Exercise production components with the browser fixture and capture deterministic screenshots:

   ```powershell
   Set-Location apps\studio
   npm run test:browser -- --grep "capture deterministic light, dark, asset and formula states"
   ```

9. Review navigation, editor, Inspector, asset menu, formula menu, dialogs, loading/error states,
   both themes, and 100%/125% scaling at full resolution.
10. Run `python scripts/check.py fast --scope studio` and the affected browser tests.

## Non-negotiable constraints

- Use only self-authored synthetic data for public screenshots.
- Keep navigation compact and stable; keep metadata secondary.
- Keep source and preview visually dominant.
- Prefer subtle surface hierarchy and separators over large cards.
- Use restrained 4–6 px radii, one low-saturation accent, and semantic colors only for status.
- Resolve modern icons through `apps/studio/src/icons.ts`.
- Preserve raw-HTML blocking, isolated preview rendering, containment-safe asset loading, and
  revision-aware write behavior.
- Do not introduce dashboard layouts, large gradients, gratuitous motion, frameless windows,
  multiple global theme frameworks, or duplicated domain logic.
- Do not refactor qbank domain or application services for a presentation-only change.
- Do not accept a modern-looking result that weakens keyboard access, focus, native behavior,
  safety warnings, or accessibility.

## Visual acceptance

The minimum modern evidence set is current Tauri light/dark main states, logical-asset menu,
formula menu, advanced filters, loading/error states, and 125% scaling. A screenshot is evidence
only after full-resolution review and must not contain a real question bank, account information,
or a machine-specific path.
