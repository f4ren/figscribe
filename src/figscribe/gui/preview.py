"""The figure preview: an image rendered exactly as the export renders it.

Deliberately not Matplotlib's FigureCanvasQTAgg: that canvas resizes the
figure to the widget, which changes the layout and breaks the promise that
the preview is the export. Here the figure keeps its size in millimetres;
only the resolution is chosen to fit the widget, and Agg draws it the same
way `export` writes a PNG. Clicks are mapped back through Matplotlib's own
hit testing, so selection works on exactly what is drawn.

The wheel zooms and dragging pans a panel; in an axis' frame, as drawn
around it when selected, they zoom and pan that axis alone. That view lives
only here, until "Use as axis range" writes it into the model. Dragging a
legend moves it, one undo step on release.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matplotlib.artist import Artist as MplArtist
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure as MplFigure
from matplotlib.transforms import Bbox
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from figscribe.commands import CommandError, Macro, SetField, find
from figscribe.gui import theme
from figscribe.gui.document import Document, axis_id, split_axis
from figscribe.gui.errors import explain
from figscribe.gui.names import size_text
from figscribe.render import render
from figscribe.render.figure import MM_PER_INCH, RIGHT, style_context
from figscribe.render.ticks import ticks_that_fit

MARGIN = 28
"""Logical pixels kept free around the figure."""
EMPTY_HINT = (
    "Drop a data file here, or use + Data and + Plot.\n"
    "The figure is drawn at its exported size."
)
CAPTION = 30
"""Room below the figure for its size and resolution."""
DRAG_THRESHOLD = 4
"""Logical pixels the mouse moves before a press becomes a drag."""
ZOOM_STEP = 1.25
"""Zoom factor of one wheel step."""
AXIS_STRIP = 8.0
"""Pixels along a panel's edge that count as its axis when clicked."""
FRAME_MARGIN = 3
"""Logical pixels between a selected object and the frame drawn around it;
in an axis' frame the wheel and dragging act on that axis."""

SETTLE_MS = 300
"""Quiet time after the last zoom or pan step before the view is rendered
again exactly; shorter, and a slow mouse waits for renders between steps."""

Limits = tuple[tuple[float, float], tuple[float, float]]


@dataclass
class _Press:
    """A pressed left button: where, and what it may turn into."""

    start: QPointF
    last: QPointF
    axes_id: str | None = None
    """The panel under the press, which a drag pans."""
    axis: str = "both"
    """"x" or "y" when the press is in an axis' frame: a drag pans only it."""
    legend: object = None
    """The Matplotlib legend under the press, which a drag moves."""
    note: object = None
    """The Matplotlib annotation under the press, which a drag moves."""

    @property
    def moving(self):
        return self.legend if self.legend is not None else self.note

    dragging: bool = False


class Preview(QWidget):
    view_changed = Signal()
    """The zoomed or panned view changed, or was dropped."""

    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.view: dict[str, Limits] = {}
        """Limits per panel id, zoomed or panned here and not (yet) in the model."""
        self._press: _Press | None = None
        self.view_bar = _ViewBar(self)
        self.view_bar.adopt.clicked.connect(self.adopt_view)
        self.view_bar.reset.clicked.connect(self.reset_view)
        self.view_bar.hide()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(200, 150)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._figure: MplFigure | None = None
        self._image: QImage | None = None
        self._origin = QPointF()
        self.error: str | None = None
        """Why the figure could not be drawn, shown instead of it."""
        self._ranges: dict[tuple[str, str], tuple[float, float]] = {}
        """The range of each axis, by (gid, "x" | "y"), when last drawn."""
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.setInterval(0)  # once the moves waiting now are applied
        self._redraw.timeout.connect(self._draw_view)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.refresh)
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        self.view = {}
        document.changed.connect(self.refresh)
        document.selection_changed.connect(self.update)
        self.refresh()

    # --- rendering ----------------------------------------------------------

    def refresh(self) -> None:
        """Render the current figure again, at a resolution that fits."""
        self._redraw.stop()
        self._settle.stop()
        self._figure, self._image, self.error = None, None, None
        model = self.document.figure
        if model is None:
            self.error = "The project has no figure."
        else:
            try:
                self._figure, self._image = self._draw(model)
            except Exception as exc:  # any failure is shown, never fatal
                self.error = f"Cannot draw the figure\n{explain(exc)}"
        self.update()

    def preview_dpi(self) -> float:
        """Dots per inch at which the current figure fits the widget."""
        model = self.document.figure
        if model is None:
            return 100.0
        ratio = self.devicePixelRatioF()
        width = max(self.width() - 2 * MARGIN, 50) * ratio
        height = max(self.height() - 2 * MARGIN - CAPTION, 50) * ratio
        fit = min(
            width / (model.width_mm / MM_PER_INCH),
            height / (model.height_mm / MM_PER_INCH),
        )
        return max(fit, 10.0)

    @property
    def redraw_pending(self) -> bool:
        """Whether a zoomed or panned view still waits to be drawn as exported."""
        return self._redraw.isActive() or self._settle.isActive()

    def _draw(self, model) -> tuple[MplFigure, QImage]:
        fig = render(model, self.document.data, view=self.view)
        known = {ax.get_gid() for ax in _all_axes(fig)}
        self.view = {oid: lim for oid, lim in self.view.items() if oid in known}
        fig.set_dpi(self.preview_dpi())
        return fig, self._paint(fig, model)

    def _draw_view(self) -> None:
        """Show the zoomed or panned view quickly on the figure drawn already,
        with the panels where they are; once the moves stop, render it again.

        Drawn twice, Matplotlib's layout moves a figure with a color bar by a
        few pixels, so only a new render looks exactly like the export. A tick
        step that no longer fits the new range, or fits again, needs one too.
        """
        model = self.document.figure
        if self._figure is None or model is None or not self._ticks_hold(model):
            self.refresh()
            return
        self._figure.set_layout_engine("none")  # half the time of a draw
        self._image = self._paint(self._figure, model)
        self.update()
        self._settle.start()

    def _ticks_hold(self, model) -> bool:
        for axes in model.axes:
            for gid, name, spec in (
                (axes.id, "x", axes.x),
                (axes.id, "y", axes.y),
                (f"{axes.id}{RIGHT}", "y", axes.y_right),
            ):
                if spec is None or (
                    spec.major_step is None and spec.minor_divisions is None
                ):
                    continue
                drawn = self._ranges.get((gid, name))
                ax = self._axes(gid)
                if drawn is None or ax is None:
                    return False
                now = ax.get_xlim() if name == "x" else ax.get_ylim()
                if ticks_that_fit(spec, drawn) != ticks_that_fit(spec, now):
                    return False
        return True

    def _paint(self, fig: MplFigure, model) -> QImage:
        canvas = FigureCanvasAgg(fig)
        with style_context(model):
            canvas.draw()
        self._ranges = {
            (ax.get_gid(), name): ax.get_xlim() if name == "x" else ax.get_ylim()
            for ax in _all_axes(fig)
            for name in ("x", "y")
        }
        buffer = np.asarray(canvas.buffer_rgba())
        height, width, _ = buffer.shape
        image = QImage(
            buffer.tobytes(), width, height, 4 * width, QImage.Format.Format_RGBA8888
        )
        image.setDevicePixelRatio(self.devicePixelRatioF())
        return image

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.refresh()
        self._place_view_bar()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(theme.GROUND))
        if self._image is None:
            self._paint_message(painter)
            return
        size = self._image.deviceIndependentSize()
        self._origin = QPointF(
            (self.width() - size.width()) / 2,
            (self.height() - CAPTION - size.height()) / 2,
        )
        paper = QRectF(self._origin, size)
        _shadow(painter, paper)
        painter.drawImage(self._origin, self._image)
        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(paper.adjusted(-0.5, -0.5, 0.5, 0.5))
        self._paint_caption(painter, paper)
        if self._is_empty():
            flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
            area = paper.adjusted(24, 24, -24, -24)
            box = painter.boundingRect(area, flags, EMPTY_HINT)
            box.adjust(-14, -10, 14, 10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.GROUND))
            painter.drawRoundedRect(box, 8, 8)
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(area, flags, EMPTY_HINT)
        box = self.selection_rect()
        if box is not None:
            painter.setPen(QPen(QColor(theme.ACCENT), 1.5, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(box, 3, 3)
        moved = self._moved_legend_rect()
        if moved is not None:
            painter.setPen(QPen(QColor(theme.ACCENT), 1.5))
            painter.setBrush(QColor(36, 89, 214, 30))
            painter.drawRoundedRect(moved, 3, 3)

    def _is_empty(self) -> bool:
        model = self.document.figure
        return model is not None and not any(a.artists for a in model.axes)

    def caption(self) -> str:
        model = self.document.figure
        if model is None:
            return ""
        size = f"{size_text(model)} · {model.dpi:g} dpi"
        if self.view:
            return f"{size} · Zoomed here only; the export keeps the set ranges"
        return f"{size} · Exactly as exported · Scroll to zoom, drag to pan"

    def _paint_caption(self, painter: QPainter, paper: QRectF) -> None:
        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor(theme.MUTED))
        area = QRectF(0, paper.bottom() + 8, self.width(), CAPTION - 8)
        painter.drawText(area, Qt.AlignmentFlag.AlignHCenter, self.caption())

    def _paint_message(self, painter: QPainter) -> None:
        if self.document.figure is None:
            title, detail = "No figure yet", "Add a figure to the project to start."
        else:
            title, _, detail = (self.error or "").partition("\n")
        box = QRectF(0, 0, min(self.width() - 2 * MARGIN, 460), 120)
        box.moveCenter(QRectF(self.rect()).center())
        font = QFont(self.font())
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.INK))
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
        painter.drawText(box, flags, title)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(box.adjusted(0, 28, 0, 0), flags, detail)

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
        for ax in _all_axes(self._figure):
            for artist in _children(ax):
                gid = artist.get_gid()
                if gid and artist.get_visible() and artist.contains(event)[0]:
                    hits.append((artist.get_zorder(), gid))
            if hits:
                return max(hits)[1]
        axis = self.axis_at(point)
        if axis is not None:
            return axis
        for ax in _all_axes(self._figure):
            if ax.get_gid() and ax.contains(event)[0]:
                return ax.get_gid()
        return None

    def axis_at(self, point: QPointF) -> str | None:
        """Selection id of the axis whose numbers or label lie at `point`."""
        if self._figure is None:
            return None
        x, y = self._to_display(point)
        for oid, boxes in self._axis_boxes():
            if any(box.contains(x, y) for box in boxes):
                return oid
        return None

    def axis_limits(self, oid: str) -> tuple[float, float] | None:
        """The range an axis shows right now, automatic or not."""
        for ax, field in self._model_axes():
            if axis_id(_host(ax), field) == oid:
                axis = ax.xaxis if field == "x" else ax.yaxis
                low, high = axis.get_view_interval()
                return (min(low, high), max(low, high))
        return None

    def _model_axes(self):
        """(Matplotlib axes, field) for every axis of a model panel."""
        if self._figure is None or self.document.figure is None:
            return
        panels = {a.id for a in self.document.figure.axes}
        for ax in _all_axes(self._figure):
            gid = ax.get_gid() or ""
            if _host(ax) not in panels:
                continue
            if gid.endswith(RIGHT):
                yield ax, "y_right"
            else:
                yield ax, "x"
                yield ax, "y"

    def _axis_boxes(self):
        """(axis selection id, boxes of its numbers, label and edge strip)."""
        renderer = self._figure.canvas.get_renderer()
        for ax, field in self._model_axes():
            axis = ax.xaxis if field == "x" else ax.yaxis
            box = ax.bbox
            strip = AXIS_STRIP
            if field == "x":
                edge = Bbox([[box.x0, box.y0 - strip], [box.x1, box.y0]])
            elif field == "y":
                edge = Bbox([[box.x0 - strip, box.y0], [box.x0, box.y1]])
            else:
                edge = Bbox([[box.x1, box.y0], [box.x1 + strip, box.y1]])
            boxes = [edge]
            if axis.label.get_visible() and axis.label.get_text():
                boxes.append(axis.label.get_window_extent(renderer))
            low, high = sorted(axis.get_view_interval())
            span = (high - low) * 1e-9
            for tick in axis.get_major_ticks():
                if not low - span <= tick.get_loc() <= high + span:
                    continue  # placed by the locator, but not drawn
                for text in (tick.label1, tick.label2):
                    if text.get_visible() and text.get_text():
                        boxes.append(text.get_window_extent(renderer))
            yield axis_id(_host(ax), field), boxes

    def selection_rect(self) -> QRectF | None:
        """Outline of the selected object, in widget coordinates."""
        oid = self.document.selected
        if self._figure is None or oid is None:
            return None
        if split_axis(oid) is not None:
            boxes = next((b for a, b in self._axis_boxes() if a == oid), [])
        else:
            boxes = [
                a.get_window_extent()
                for ax in _all_axes(self._figure)
                for a in (ax, *_children(ax))
                if a.get_gid() == oid and a.get_visible()
            ]
        frame = self._frame(boxes)
        if frame is None:
            return None
        return QRectF(
            self._to_widget(frame.x0, frame.y1), self._to_widget(frame.x1, frame.y0)
        )

    def _frame(self, boxes) -> Bbox | None:
        """The outline drawn around `boxes` when selected, in display units."""
        boxes = [b for b in boxes if np.all(np.isfinite(b.extents)) and b.width >= 0]
        if not boxes:
            return None
        return Bbox.union(boxes).padded(FRAME_MARGIN * self.devicePixelRatioF())

    # --- zoom, pan and the legend ---------------------------------------------

    def axes_at(self, point: QPointF):
        """The Matplotlib axes under `point` (insets first), or None."""
        if self._figure is None:
            return None
        x, y = self._to_display(point)
        # Only panels: a colour bar or a right y axis has its own Matplotlib axes.
        panels = {a.id for a in self.document.figure.axes}
        for ax in _all_axes(self._figure):
            if ax.get_gid() in panels and ax.bbox.contains(x, y):
                return ax
        return None

    def zoom(self, point: QPointF, factor: float, axis: str = "both") -> None:
        """Zoom the panel under `point` by `factor` (> 1 zooms in), keeping
        the spot under the cursor in place; `axis` limits it to "x" or "y".
        Over an axis' numbers or label, only that axis zooms."""
        ax = self.axes_at(point)
        if ax is None and axis == "both":
            ax, axis = self._axis_under(point)
        if ax is None:
            return
        x, y = self._to_display(point)
        box = ax.bbox
        xs = (x - (x - box.x0) / factor, x + (box.x1 - x) / factor)
        ys = (y - (y - box.y0) / factor, y + (box.y1 - y) / factor)
        if axis == "y":
            xs = (box.x0, box.x1)
        if axis == "x":
            ys = (box.y0, box.y1)
        self._set_view(ax, xs, ys)

    def _axis_under(self, point: QPointF):
        """(Matplotlib axes, "x" or "y") of the axis whose frame, as drawn
        around it when selected, is under `point`; (None, "both") if none."""
        if self._figure is None:
            return None, "both"
        x, y = self._to_display(point)
        oid = next(
            (
                oid
                for oid, boxes in self._axis_boxes()
                if (frame := self._frame(boxes)) is not None and frame.contains(x, y)
            ),
            None,
        )
        if oid is None:
            return None, "both"
        axes_id, field = split_axis(oid)
        if field == "y_right":
            return self._axes(axes_id + RIGHT), "y"
        return self._axes(axes_id), field

    def pan(self, axes_id: str, dx: float, dy: float, axis: str = "both") -> None:
        """Move the view of panel `axes_id` with the mouse by (dx, dy) logical
        pixels: the data follows the cursor; `axis` limits it to "x" or "y"."""
        ax = self._axes(axes_id)
        if ax is None:
            return
        if axis == "x":
            dy = 0
        elif axis == "y":
            dx = 0
        ratio = self.devicePixelRatioF()
        box = ax.bbox
        dx, dy = dx * ratio, -dy * ratio  # display y grows upwards
        self._set_view(ax, (box.x0 - dx, box.x1 - dx), (box.y0 - dy, box.y1 - dy))

    def reset_view(self) -> None:
        """Back to the limits in the model, as exported."""
        if self.view:
            self.view = {}
            self.refresh()  # the model's ranges may be automatic: render them
            self.view_changed.emit()
            self._place_view_bar()

    def adopt_view(self) -> None:
        """Write the zoomed or panned view into the model as axis ranges."""
        if not self.view:
            return
        steps = []
        for oid, (xlim, ylim) in self.view.items():
            steps += [
                SetField(oid, ("x", "limits"), (float(xlim[0]), float(xlim[1]))),
                SetField(oid, ("y", "limits"), (float(ylim[0]), float(ylim[1]))),
            ]
        self.view = {}
        self.document.push(Macro("Use the view as axis ranges", steps))
        self.view_changed.emit()
        self._place_view_bar()

    def move_legend(self, axes_id: str, dx: float, dy: float) -> None:
        """Move the legend of panel `axes_id` by (dx, dy) logical pixels, as
        one undo step: its lower left corner gets a fixed place in the panel."""
        ax = self._axes(axes_id)
        legend = ax.get_legend() if ax is not None else None
        if legend is None:
            return
        ratio = self.devicePixelRatioF()
        box = legend.get_window_extent()
        x0, y0 = box.x0 + dx * ratio, box.y0 - dy * ratio
        fx, fy = ax.transAxes.inverted().transform((x0, y0))
        # Matplotlib keeps borderaxespad between the anchor and the frame.
        pad = legend.borderaxespad * legend.prop.get_size_in_points()
        pad *= self._figure.dpi / 72
        position = (float(fx - pad / ax.bbox.width), float(fy - pad / ax.bbox.height))
        self.document.push(SetField(axes_id, ("legend", "position"), position))

    def _axes(self, axes_id: str):
        if self._figure is None:
            return None
        return next(
            (a for a in _all_axes(self._figure) if a.get_gid() == axes_id), None
        )

    def _set_view(self, ax, xs, ys) -> None:
        inverse = ax.transData.inverted()
        (x0, y0), (x1, y1) = inverse.transform([(xs[0], ys[0]), (xs[1], ys[1])])
        self.view[ax.get_gid()] = ((float(x0), float(x1)), (float(y0), float(y1)))
        # At once on the drawn figure, so that the next move starts from here;
        # drawing it waits until the moves already queued are applied too.
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        self._redraw.start()
        self.view_changed.emit()
        self._place_view_bar()

    def _place_view_bar(self) -> None:
        self.view_bar.setVisible(bool(self.view))
        self.view_bar.adjustSize()
        width = self.view_bar.width()
        self.view_bar.move(max(0, (self.width() - width) // 2), 8)

    def _moved_legend_rect(self) -> QRectF | None:
        press = self._press
        if press is None or press.moving is None or not press.dragging:
            return None
        box = press.moving.get_window_extent()
        rect = QRectF(self._to_widget(box.x0, box.y1), self._to_widget(box.x1, box.y0))
        return rect.translated(press.last - press.start)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt naming
        steps = event.angleDelta().y() / 120
        if not steps:
            return
        modifiers = event.modifiers()
        axis = "both"
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            axis = "x"
        elif modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        ):
            axis = "y"
        self.zoom(event.position(), ZOOM_STEP**steps, axis)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        point = event.position()
        if self._figure is None:
            self.document.select(None)
            return
        ax, axis = self.axes_at(point), "both"
        if ax is None:
            ax, axis = self._axis_under(point)
        legend = self._legend_at(point)
        self._press = _Press(
            point,
            point,
            axes_id=ax.get_gid() if ax is not None else None,
            axis=axis,
            legend=legend,
            note=self._note_at(point) if legend is None else None,
        )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        press = self._press
        if press is None:
            return
        point = event.position()
        if not press.dragging:
            moved = point - press.start
            if abs(moved.x()) + abs(moved.y()) < DRAG_THRESHOLD:
                return
            press.dragging = True
        if press.moving is None and press.axes_id is not None:
            delta = point - press.last
            self.pan(press.axes_id, delta.x(), delta.y(), press.axis)
        press.last = point
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        press, self._press = self._press, None
        if press is None or event.button() != Qt.MouseButton.LeftButton:
            return
        if not press.dragging:
            self.document.select(self.object_at(press.start))
        elif press.legend is not None:
            moved = event.position() - press.start
            self.move_legend(press.legend.get_gid(), moved.x(), moved.y())
        elif press.note is not None:
            moved = event.position() - press.start
            self.move_note(press.note.get_gid(), moved.x(), moved.y())
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape and self.view:
            self.reset_view()
            return
        super().keyPressEvent(event)

    def move_note(self, note_id: str, dx: float, dy: float) -> None:
        """Move the note `note_id` by (dx, dy) logical pixels, as one undo
        step, in the coordinates it is placed in; an arrow keeps its tip."""
        try:
            note = find(self.document.project, note_id)
        except CommandError:
            return
        found = [
            (ax, t)
            for ax in _all_axes(self._figure)
            for t in ax.texts
            if t.get_gid() == note_id
        ]
        if not found:
            return
        ax = found[0][0]
        transform = ax.transAxes if note.coords == "axes" else ax.transData
        ratio = self.devicePixelRatioF()
        x, y = transform.transform(note.position)
        new = transform.inverted().transform((x + dx * ratio, y - dy * ratio))
        position = (float(new[0]), float(new[1]))
        self.document.push(SetField(note_id, ("position",), position))

    def _note_at(self, point: QPointF):
        x, y = self._to_display(point)
        event = MouseEvent("button_press_event", self._figure.canvas, x, y)
        for ax in _all_axes(self._figure):
            for text in ax.texts:
                if text.get_gid() and text.get_visible() and text.contains(event)[0]:
                    return text
        return None

    def _legend_at(self, point: QPointF):
        x, y = self._to_display(point)
        event = MouseEvent("button_press_event", self._figure.canvas, x, y)
        for ax in _all_axes(self._figure):
            legend = ax.get_legend()
            if legend is not None and legend.get_gid() and legend.contains(event)[0]:
                return legend
        return None

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


def _host(ax) -> str:
    """The model panel id of a Matplotlib axes, also of its right twin."""
    gid = ax.get_gid() or ""
    return gid[: -len(RIGHT)] if gid.endswith(RIGHT) else gid


def _all_axes(fig: MplFigure) -> list:
    """Every axes, insets first: they lie on top of the panel they sit in."""
    insets = [child for ax in fig.axes for child in ax.child_axes]
    return [*insets, *fig.axes]


def _children(ax) -> list[MplArtist]:
    """The artists of an axes that carry a model id, the legend included."""
    found = [a for a in ax.get_children() if a.get_gid()]
    # An errorbar is a container; its lines and caps carry the gid themselves.
    for container in ax.containers:
        for part in container.get_children():
            if part.get_gid() and part not in found:
                found.append(part)
    return found


def _shadow(painter: QPainter, paper: QRectF) -> None:
    """A soft drop shadow, so the figure reads as a sheet of paper."""
    painter.setPen(Qt.PenStyle.NoPen)
    for step in range(8, 0, -1):
        painter.setBrush(QColor(0, 0, 0, 4 + (8 - step)))
        spread = paper.adjusted(-step, -step + 3, step, step + 3)
        painter.drawRoundedRect(spread, step, step)


class _ViewBar(QWidget):
    """Shown while a panel is zoomed or panned: keep it, or go back."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("viewBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 8, 6)
        row.setSpacing(10)
        row.addWidget(QLabel("Zoomed in the preview only"))
        self.adopt = QPushButton("Use as axis range")
        self.adopt.setObjectName("primary")
        self.reset = QPushButton("Reset")
        row.addWidget(self.adopt)
        row.addWidget(self.reset)
