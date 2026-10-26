"""Every marker Matplotlib draws, by name, and a small picture of each, for
the lists the marker fields are chosen from."""

from __future__ import annotations

from matplotlib.markers import MarkerStyle
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from figscribe.gui import theme
from figscribe.model.artists import LIKE_THE_PLOT

__all__ = ["LIKE_THE_PLOT", "MARKERS", "marker_icon"]

MARKERS = [
    ("o", "Circle"),
    ("s", "Square"),
    ("^", "Triangle up"),
    ("v", "Triangle down"),
    ("<", "Triangle left"),
    (">", "Triangle right"),
    ("D", "Diamond"),
    ("d", "Thin diamond"),
    ("p", "Pentagon"),
    ("h", "Hexagon"),
    ("H", "Hexagon, on its side"),
    ("8", "Octagon"),
    ("*", "Star"),
    ("P", "Plus, filled"),
    ("X", "Cross, filled"),
    ("+", "Plus"),
    ("x", "Cross"),
    ("1", "Tri down"),
    ("2", "Tri up"),
    ("3", "Tri left"),
    ("4", "Tri right"),
    ("|", "Vertical line"),
    ("_", "Horizontal line"),
    (".", "Point"),
    (",", "Pixel"),
]
"""Matplotlib's markers, the common ones first."""


def marker_icon(marker: str | None, size: int = 16) -> QIcon:
    """`marker` drawn as Matplotlib draws it; an empty icon for none."""
    pixmap = QPixmap(size * 2, size * 2)  # sharp on high-density screens
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    if marker is None or marker not in dict(MARKERS):
        return QIcon(pixmap)
    style = MarkerStyle(marker)
    path = style.get_path().transformed(style.get_transform())
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Scaled by its own reach, so that a diamond's corners stay inside.
    reach = max(float(abs(path.vertices).max()), 1e-9)
    scale = size * 0.4 / reach
    outline = QPainterPath()
    for polygon in path.to_polygons(closed_only=False):
        points = [
            QPointF(size / 2 + x * scale, size / 2 - y * scale) for x, y in polygon
        ]
        if not points:
            continue
        outline.moveTo(points[0])
        for point in points[1:]:
            outline.lineTo(point)
    ink = QColor(theme.INK)
    painter.setPen(QPen(ink, 1.2))
    if style.is_filled() and marker not in (",", "."):
        painter.setBrush(ink)
    painter.drawPath(outline)
    painter.end()
    return QIcon(pixmap)
