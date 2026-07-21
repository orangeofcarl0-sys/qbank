"""Resolved design tokens used by every Studio surface."""

from dataclasses import dataclass

from qbank.presentation.studio.design.metrics import METRICS, Metrics
from qbank.presentation.studio.design.palette import Palette, ThemeName, palette_for
from qbank.presentation.studio.design.typography import TYPOGRAPHY, Typography


@dataclass(frozen=True, slots=True)
class DesignTokens:
    """One immutable theme snapshot."""

    theme: ThemeName
    palette: Palette
    metrics: Metrics = METRICS
    typography: Typography = TYPOGRAPHY


def tokens_for(theme: ThemeName) -> DesignTokens:
    """Resolve all Studio tokens for a theme name."""
    return DesignTokens(theme=theme, palette=palette_for(theme))
