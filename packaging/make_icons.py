"""Make the installers' icons from the application icon's SVG drawings.

Run it after changing src/figscribe/gui/icons/figscribe*.svg and commit what
it writes to packaging/icons:

    python packaging/make_icons.py

- figscribe.icns, macOS: the full drawing at every size, as macOS icons keep
  their margin even in lists.
- figscribe.ico, Windows: 16 to 256 px, the small drawing up to 48 px, as in
  the window icon.
- figscribe.png, 1024 px, for Linux and anything else that wants one image.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

from figscribe.gui import theme

ICNS_SIZES = (32, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _pillow(size: int, drawing: Path | None = None) -> Image.Image:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    theme.render_app_icon(size, drawing).save(buffer, "PNG")
    return Image.open(io.BytesIO(buffer.data().data()))


def make_icons(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    full = theme.app_icon_svg(1024)
    icns = [_pillow(size, full) for size in ICNS_SIZES]
    icns[-1].save(folder / "figscribe.icns", append_images=icns[:-1])
    ico = [_pillow(size) for size in ICO_SIZES]
    ico[-1].save(
        folder / "figscribe.ico",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=ico[:-1],
    )
    icns[-1].save(folder / "figscribe.png")


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    make_icons(Path(__file__).parent / "icons")
