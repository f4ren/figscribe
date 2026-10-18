"""The figure preview: an image rendered exactly as the export renders it.

Deliberately not Matplotlib's FigureCanvasQTAgg: that canvas resizes the
figure to the widget, which changes the layout and breaks the promise that
the preview is the export. Here the figure keeps its size in millimetres;
only the resolution is chosen to fit the widget, and Agg draws it the same
way `export` writes a PNG. Clicks are mapped back through Matplotlib's own
hit testing, so selection works on exactly what is drawn.
"""

from __future__ import annotations

import numpy as np
from matplotlib.artist import Artist as MplArtist
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure as MplFigure
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from figscribe.gui.document import Document
from figscribe.render import render
from figscribe.render.figure import MM_PER_INCH, style_context

MARGIN = 12
"""Logical pixels kept free around the figure."""


class Preview(QWidget):
    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 150)
        self.setAutoFillBackground(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._figure: MplFigure | None = None
        self._image: QImage | None = None
        self._origin = QPointF()
        self.error: str | None = None
        """Why the figure could not be drawn, shown instead of it."""
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(self.refresh)
        document.selection_changed.connect(self.update)
        self.refresh()

    # --- rendering ----------------------------------------------------------

    def refresh(self) -> None:
        """Render the current figure again, at a resolution that fits."""
        self._figure, self._image, self.error = None, None, None
        model = self.document.figure
        if model is None:
            self.error = "The project has no figure."
        else:
            try:
                self._figure, self._image = self._draw(model)
            except Exception as exc:  # any failure is shown, never fatal
                self.error = f"Cannot draw the figure:\n{exc}"
        self.update()

    def preview_dpi(self) -> float:
        """Dots per inch at which the current figure fits the widget."""
        model = self.document.figure
        if model is None:
            return 100.0
        ratio = self.devicePixelRatioF()
        width = max(self.width() - 2 * MARGIN, 50) * ratio
        height = max(self.height() - 2 * MARGIN, 50) * ratio
        fit = min(
            width / (model.width_mm / MM_PER_INCH),
            height / (model.height_mm / MM_PER_INCH),
        )
        return max(fit, 10.0)

    def _draw(self, model) -> tuple[MplFigure, QImage]:
        fig = render(model, self.document.data)
        fig.set_dpi(self.preview_dpi())
        canvas = FigureCanvasAgg(fig)
        with style_context(model):
            canvas.draw()
        buffer = np.asarray(canvas.buffer_rgba())
        height, width, _ = buffer.shape
        image = QImage(
            buffer.tobytes(), width, height, 4 * width, QImage.Format.Format_RGBA8888
        )
        image.setDevicePixelRatio(self.devicePixelRatioF())
        return fig, image

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.refresh()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        if self._image is None:
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, self.error or ""
            )
            return
        size = self._image.deviceIndependentSize()
        self._origin = QPointF(
            (self.width() - size.width()) / 2, (self.height() - size.height()) / 2
        )
        painter.drawImage(self._origin, self._image)
        box = self.selection_rect()
        if box is not None:
            painter.setPen(QPen(QColor(30, 120, 220), 1.5, Qt.PenStyle.DashLine))
            painter.drawRect(box)

    # --- selection ----------------------------------------------------------

    def object_at(self, point: QPointF) -> str | None:
        """Id of the model object drawn at `point`, in widget coordinates.

        Artists win over the axes they sit in; the topmost artist wins.
        """
        if self._figure is None:
            return None
        x, y = self._to_display(point)
        event = MouseEvent("button_press_event", self._figure.canvas, x, y)
        hits: list[tuple[float, str]] = []
        for ax in self._figure.axes:
            for artist in _children(ax):
                gid = artist.get_gid()
                if gid and artist.get_visible() and artist.contains(event)[0]:
                    hits.append((artist.get_zorder(), gid))
            if hits:
                return max(hits)[1]
        for ax in self._figure.axes:
            if ax.get_gid() and ax.contains(event)[0]:
                return ax.get_gid()
        return None

    def selection_rect(self) -> QRectF | None:
        """Outline of the selected object, in widget coordinates."""
        oid = self.document.selected
        if self._figure is None or oid is None:
            return None
        boxes = [
            a.get_window_extent()
            for ax in self._figure.axes
            for a in (ax, *_children(ax))
            if a.get_gid() == oid and a.get_visible()
        ]
        boxes = [b for b in boxes if np.all(np.isfinite(b.extents)) and b.width >= 0]
        if not boxes:
            return None
        x0 = min(b.x0 for b in boxes)
        x1 = max(b.x1 for b in boxes)
        y0 = min(b.y0 for b in boxes)
        y1 = max(b.y1 for b in boxes)
        top_left = self._to_widget(x0, y1)
        bottom_right = self._to_widget(x1, y0)
        return QRectF(top_left, bottom_right).adjusted(-3, -3, 3, 3)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.document.select(self.object_at(event.position()))
        super().mousePressEvent(event)

    # Matplotlib's display coordinates are device pixels from the bottom left.

    def _to_display(self, point: QPointF) -> tuple[float, float]:
        ratio = self.devicePixelRatioF()
        height = self._figure.bbox.height
        return (
            (point.x() - self._origin.x()) * ratio,
            height - (point.y() - self._origin.y()) * ratio,
        )

    def _to_widget(self, x: float, y: float) -> QPointF:
        ratio = self.devicePixelRatioF()
        height = self._figure.bbox.height
        return QPointF(
            self._origin.x() + x / ratio, self._origin.y() + (height - y) / ratio
        )


def _children(ax) -> list[MplArtist]:
    """The artists of an axes that carry a model id, the legend included."""
    found = [a for a in ax.get_children() if a.get_gid()]
    # An errorbar is a container; its lines and caps carry the gid themselves.
    for container in ax.containers:
        for part in container.get_children():
            if part.get_gid() and part not in found:
                found.append(part)
    return found
