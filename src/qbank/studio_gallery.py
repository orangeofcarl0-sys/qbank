"""Run the qbank Studio component gallery."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import cast

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from qbank.presentation.studio.design.palette import ThemeName
from qbank.presentation.studio.design.stylesheet import apply_theme
from qbank.presentation.studio.gallery import StudioGallery


def main() -> int:
    """Launch the interactive gallery or save a deterministic screenshot."""
    parser = argparse.ArgumentParser(description="qbank Studio component gallery")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--scale", choices=("1", "1.25"), default="1")
    args = parser.parse_args()
    os.environ.setdefault("QT_SCALE_FACTOR", args.scale)
    application = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
    application.setApplicationName("qbank Studio Gallery")
    theme = cast(ThemeName, args.theme)
    apply_theme(application, theme)
    gallery = StudioGallery(theme)
    gallery.show()
    if args.capture is not None:
        args.capture.parent.mkdir(parents=True, exist_ok=True)

        def capture() -> None:
            gallery.grab().save(str(args.capture), "PNG")
            application.quit()

        QTimer.singleShot(3600, capture)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
