"""Typography tokens shared with Qt and embedded web surfaces."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Typography:
    """Conservative Windows-first type scale."""

    qt_family: str = "Microsoft YaHei UI"
    ui_family: str = '"Segoe UI", "Microsoft YaHei UI", sans-serif'
    document_family: str = '"Segoe UI", "Microsoft YaHei UI", sans-serif'
    mono_family: str = '"Cascadia Mono", "Consolas", monospace'
    ui_size: int = 13
    document_size: int = 15
    small_size: int = 12
    title_size: int = 21
    line_height: float = 1.62


TYPOGRAPHY = Typography()
