"""Semantic Studio palettes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ThemeName = Literal["light", "dark"]


@dataclass(frozen=True, slots=True)
class Palette:
    """Colors named by purpose instead of widget implementation."""

    background: str
    surface: str
    surface_elevated: str
    surface_hover: str
    border_subtle: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_disabled: str
    accent: str
    accent_hover: str
    selection: str
    focus: str
    success: str
    warning: str
    error: str


LIGHT = Palette(
    background="#f3f4f6",
    surface="#fbfbfc",
    surface_elevated="#ffffff",
    surface_hover="#eef1f5",
    border_subtle="#dfe2e7",
    border_strong="#c5cad2",
    text_primary="#20242a",
    text_secondary="#606975",
    text_disabled="#9299a3",
    accent="#476d91",
    accent_hover="#365d82",
    selection="#dce8f3",
    focus="#5b83a8",
    success="#39745a",
    warning="#9a651e",
    error="#a44747",
)

DARK = Palette(
    background="#1c1f23",
    surface="#24282d",
    surface_elevated="#2b3036",
    surface_hover="#333941",
    border_subtle="#383e46",
    border_strong="#505862",
    text_primary="#eef1f4",
    text_secondary="#b3bac3",
    text_disabled="#767e88",
    accent="#7899b8",
    accent_hover="#8cabc7",
    selection="#334b60",
    focus="#91b4d3",
    success="#6fa98a",
    warning="#d0a35f",
    error="#d37b7b",
)


def palette_for(theme: ThemeName) -> Palette:
    """Return the immutable semantic palette for a theme."""
    return DARK if theme == "dark" else LIGHT
