"""Density and geometry tokens for Studio."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Metrics:
    """Compact editor metrics in device-independent pixels."""

    space_1: int = 4
    space_2: int = 8
    space_3: int = 12
    space_4: int = 16
    space_6: int = 24
    space_8: int = 32
    radius_small: int = 4
    radius_medium: int = 6
    control_height: int = 30
    toolbar_height: int = 38
    nav_width: int = 246
    icon_small: int = 14
    icon_normal: int = 16
    border_width: int = 1


METRICS = Metrics()
