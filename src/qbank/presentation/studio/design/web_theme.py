"""CSS variables and state documents for embedded Studio web views."""

from __future__ import annotations

import html

from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.tokens import tokens_for


def css_variables(theme: ThemeName) -> str:
    """Generate the shared CSS custom properties for CodeMirror and preview."""
    t = tokens_for(theme)
    p, m, ty = t.palette, t.metrics, t.typography
    values = {
        "background": p.background,
        "surface": p.surface,
        "surface-elevated": p.surface_elevated,
        "surface-hover": p.surface_hover,
        "border-subtle": p.border_subtle,
        "border-strong": p.border_strong,
        "text-primary": p.text_primary,
        "text-secondary": p.text_secondary,
        "text-disabled": p.text_disabled,
        "accent": p.accent,
        "accent-hover": p.accent_hover,
        "selection": p.selection,
        "focus": p.focus,
        "success": p.success,
        "warning": p.warning,
        "error": p.error,
        "radius-small": f"{m.radius_small}px",
        "radius-medium": f"{m.radius_medium}px",
        "space-1": f"{m.space_1}px",
        "space-2": f"{m.space_2}px",
        "space-3": f"{m.space_3}px",
        "space-4": f"{m.space_4}px",
        "ui-font": ty.ui_family,
        "document-font": ty.document_family,
        "mono-font": ty.mono_family,
    }
    return (
        f":root{{color-scheme:{theme};"
        + "".join(f"--qbank-{name}:{value};" for name, value in values.items())
        + "}"
    )


def state_page(theme: ThemeName, title: str, detail: str, *, state: str = "loading") -> str:
    """Create a themed loading or error preview document."""
    role = "error" if state == "error" else "text-secondary"
    aria_role = "alert" if state == "error" else "status"
    aria_live = "assertive" if state == "error" else "polite"
    return f"""<!doctype html><html><head><meta charset='utf-8'><style>
    {css_variables(theme)}
    body{{margin:0;padding:34px;background:var(--qbank-surface-elevated);color:var(--qbank-text-primary);font:14px/1.6 var(--qbank-ui-font)}}
    .state{{max-width:580px;border-left:3px solid var(--qbank-{role});padding:4px 16px}}
    h2{{margin:0 0 4px;font-size:16px}}p{{margin:0;color:var(--qbank-text-secondary)}}
    </style></head><body><div class='state' role='{aria_role}' aria-live='{aria_live}'><h2>{html.escape(title)}</h2><p>{html.escape(detail)}</p></div></body></html>"""
