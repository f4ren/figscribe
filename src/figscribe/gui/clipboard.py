"""The figure on the system clipboard."""

from __future__ import annotations

from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication, QImage

_put: QMimeData | None = None
"""What `put_figure` left on the clipboard, while it is still there."""
_hooked = False


def put_figure(png: bytes, svg: bytes) -> None:
    """Put the figure on the clipboard as PNG and SVG, and as a bitmap for
    programs that read neither (Office on Windows)."""
    global _put, _hooked
    mime = QMimeData()
    mime.setData("image/png", png)
    mime.setData("image/svg+xml", svg)
    mime.setImageData(QImage.fromData(png))
    QGuiApplication.clipboard().setMimeData(mime)
    _put = mime
    if not _hooked:
        # Qt deletes what is on the clipboard when the process ends, after
        # Python has shut down: a mime data made here then crashes the exit.
        QGuiApplication.instance().aboutToQuit.connect(release)
        _hooked = True


def release() -> None:
    """Before the program ends: if the figure is still on the clipboard,
    leave its bitmap there instead, which Qt owns and can delete safely. The
    SVG is not kept past the end of the program."""
    global _put
    clipboard = QGuiApplication.clipboard()
    if _put is not None and clipboard.mimeData() is _put:
        clipboard.setImage(QImage.fromData(bytes(_put.data("image/png"))))
    _put = None
