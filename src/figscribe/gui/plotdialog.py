"""Adding a plot: its kind as a tile, its columns as a sentence, a preview of
it with the data, and the panel it goes into."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.gui import theme
from figscribe.gui.errors import explain
from figscribe.gui.widgets import label, rule
from figscribe.model import (
    ArrayRef,
    ArtistBase,
    Axes,
    AxisSpec,
    Colorbar,
    ColorMesh,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    Histogram,
    ImagePlot,
    LinePlot,
    ScatterPlot,
)
from figscribe.render.figure import DataProvider, render
from figscribe.suggest import error_columns

KINDS: dict[str, tuple[type[ArtistBase], str]] = {
    "Line": (LinePlot, "line"),
    "Points": (ScatterPlot, "scatter"),
    "Error bars": (ErrorbarPlot, "errorbar"),
    "Histogram": (Histogram, "histogram"),
    "Image": (ImagePlot, "image"),
    "Color mesh": (ColorMesh, "colormesh"),
}
"""The tiles, in order: the kind each makes and its icon."""
TWO_D = (ImagePlot, ColorMesh)

NEW_PANEL = "new panel"
"""The target that puts the plot into a new panel to the right."""

PREVIEW_SIZE = (300, 220)
"""Of the preview, in pixels at a screen scale of 1."""


class PlotDialog(QDialog):
    """Asks for a plot of two (or, with error bars, up to four) columns, or
    of one 2-D array, and where it goes.

    `targets` are (name, Axes.id) to choose from, `target` the one chosen at
    first; without them the dialog does not ask. `data` draws the preview;
    without it there is none. `summary` says what the data is.
    """

    def __init__(
        self,
        columns: Sequence[tuple[str, ColumnRef]],
        parent=None,
        arrays: Sequence[tuple[str, ArrayRef]] = (),
        *,
        targets: Sequence[tuple[str, str]] = (),
        target: str | None = None,
        data: DataProvider | None = None,
        summary: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("Add plot")
        self.columns = list(columns)
        self.data = data
        self._errors = _errors_of(self.columns)

        self.target = QComboBox()
        for text, oid in targets:
            self.target.addItem(text, oid)
        if target is not None and self.target.findData(target) >= 0:
            self.target.setCurrentIndex(self.target.findData(target))
        self.summary = label(summary, "caption")

        self.kinds = QButtonGroup(self)
        self.kinds.setExclusive(True)
        self.tiles: dict[str, QPushButton] = {}
        for name, (cls, glyph) in KINDS.items():
            tile = _kind_tile(name, glyph)
            if cls in TWO_D and not arrays:
                tile.setEnabled(False)
                tile.setToolTip(
                    f"{name} needs 2-D data: import a .npy or .npz file, or "
                    "draw a whole table of numbers."
                )
            elif cls not in TWO_D and not columns:
                tile.setEnabled(False)
                tile.setToolTip(f"{name} needs columns: import a CSV file.")
            self.kinds.addButton(tile)
            self.tiles[name] = tile

        single = len({ref.source for _, ref in self.columns}) == 1
        self.array = QComboBox()
        for text, ref in arrays:
            self.array.addItem(text, ref)
        self.y = self._column_box(single, optional=False)
        self.x = self._column_box(single, optional=False)
        self.yerr = self._column_box(single, optional=True)
        self.xerr = self._column_box(single, optional=True)
        self.label = QLineEdit()
        self.label.setPlaceholderText("not in the legend")
        self.hint = label("", "caption")
        self.preview = QLabel()
        self.preview.setObjectName("plotPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        width, height = PREVIEW_SIZE
        self.preview.setFixedSize(width + 2, height + 2)  # and its border

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.add = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add.setText("Add plot")
        self.add.setObjectName("primary")
        self.add.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._layout(bool(targets))

        # A sensible start: y is the second column, against the first; with
        # an error column for it, error bars.
        if len(self.columns) > 1:
            self.y.setCurrentIndex(1)
        self._take_error()
        self._take_label()
        start = "Error bars" if self.yerr.currentData() is not None else "Line"
        if not self.tiles[start].isEnabled():
            start = next(n for n, t in self.tiles.items() if t.isEnabled())
        self.tiles[start].setChecked(True)

        self.kinds.buttonToggled.connect(lambda _, checked: checked and self._update())
        self.y.activated.connect(self._y_chosen)
        for box in (self.x, self.yerr, self.xerr, self.array):
            box.activated.connect(self._update)
        self.label.editingFinished.connect(self._update)
        self._update()

    # --- what was chosen ----------------------------------------------------

    @property
    def kind(self) -> type[ArtistBase]:
        button = self.kinds.checkedButton()
        name = next(n for n, tile in self.tiles.items() if tile is button)
        return KINDS[name][0]

    def target_id(self) -> str | None:
        """The Axes.id chosen, NEW_PANEL, or None when the dialog did not ask."""
        return self.target.currentData()

    def artist(self) -> ArtistBase:
        """The plot as chosen."""
        cls = self.kind
        if cls is ImagePlot:
            return ImagePlot(data=self.array.currentData(), colorbar=Colorbar())
        if cls is ColorMesh:
            return ColorMesh(c=self.array.currentData(), colorbar=Colorbar())
        if cls is Histogram:
            return Histogram(
                values=self.y.currentData(), label=self.label.text() or None
            )
        fields = {
            "x": self.x.currentData(),
            "y": self.y.currentData(),
            "label": self.label.text() or None,
        }
        if cls is ErrorbarPlot:
            fields["yerr"] = self.yerr.currentData()
            fields["xerr"] = self.xerr.currentData()
        return cls(**fields)

    # --- layout ---------------------------------------------------------------

    def _layout(self, with_target: bool) -> None:
        heading = QHBoxLayout()
        heading.addWidget(label("Add a plot", "dialogTitle"), 1)
        if with_target:
            heading.addWidget(label("to", "caption"))
            heading.addWidget(self.target)
        top = QVBoxLayout()
        top.setContentsMargins(24, 20, 24, 16)
        top.setSpacing(4)
        top.addLayout(heading)
        top.addWidget(self.summary)

        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        for tile in self.tiles.values():
            tiles.addWidget(tile)
        tiles.addStretch(1)

        self.form = QFormLayout()
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(8)
        self.y_caption = QLabel("Plot")
        self.form.addRow(self.y_caption, self.y)
        self.form.addRow("against", self.x)
        self.form.addRow("± y error", self.yerr)
        self.form.addRow("± x error", self.xerr)
        self.form.addRow("Data", self.array)
        self.form.addRow("Legend", self.label)

        left = QVBoxLayout()
        left.setContentsMargins(24, 16, 24, 16)
        left.setSpacing(16)
        left.addLayout(tiles)
        left.addLayout(self.form)
        left.addWidget(self.hint)
        left.addStretch(1)

        aside = QWidget()
        aside.setObjectName("aside")
        right = QVBoxLayout(aside)
        right.setContentsMargins(20, 16, 20, 16)
        right.addWidget(label("Preview", "sectionHeading"))
        right.addWidget(self.preview)
        right.addStretch(1)
        if self.data is None:
            aside.hide()

        middle = QHBoxLayout()
        middle.setSpacing(0)
        middle.addLayout(left, 1)
        middle.addWidget(aside)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(24, 12, 24, 16)
        bottom.addWidget(
            label("Everything can be changed later in the property panel.", "caption"),
            1,
        )
        bottom.addWidget(self.buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(rule())
        layout.addLayout(middle, 1)
        layout.addWidget(rule())
        layout.addLayout(bottom)

    def _column_box(self, single: bool, optional: bool) -> QComboBox:
        box = QComboBox()
        if optional:
            box.addItem("none", None)
        for text, ref in self.columns:
            box.addItem(str(ref.column) if single else text, ref)
        return box

    # --- reacting -------------------------------------------------------------

    def _y_chosen(self) -> None:
        self._take_error()
        self._take_label()
        self._update()

    def _take_error(self) -> None:
        """The error column of the chosen y, if a column is named as one."""
        error = self._errors.get(_key(self.y.currentData()))
        self.yerr.setCurrentIndex(max(self.yerr.findData(error), 0))

    def _take_label(self) -> None:
        ref = self.y.currentData()
        if ref is not None and isinstance(ref.column, str):
            self.label.setText(ref.column)

    def _update(self) -> None:
        kind = self.kind
        two_d = kind in TWO_D
        shown = {
            self.y: not two_d,
            self.x: kind not in (Histogram, *TWO_D),
            self.yerr: kind is ErrorbarPlot,
            self.xerr: kind is ErrorbarPlot,
            self.array: two_d,
            self.label: not two_d,  # the colour bar explains it
        }
        for widget, visible in shown.items():
            self.form.setRowVisible(widget, visible)
        self.y_caption.setText("Values" if kind is Histogram else "Plot")
        error, value = self.yerr.currentData(), self.y.currentData()
        named = error is not None and self._errors.get(_key(value)) == error
        self.hint.setText(
            f"{error.column} looks like the error of {value.column}."
            if kind is ErrorbarPlot and named
            else ""
        )
        self._draw_preview()

    def _draw_preview(self) -> None:
        if self.data is None:
            return
        try:
            image = preview_image(self.artist(), self.data, self.devicePixelRatioF())
        except Exception as exc:  # any failure is shown, never fatal
            self.preview.setPixmap(QPixmap())
            self.preview.setMargin(10)
            self.preview.setText(f"Cannot draw this\n{explain(exc)}")
            return
        self.preview.setMargin(0)
        self.preview.setText("")
        self.preview.setPixmap(QPixmap.fromImage(image))


def preview_image(artist: ArtistBase, data: DataProvider, scale: float) -> QImage:
    """`artist` alone in a small panel, its axes named after its columns."""
    labels = {}
    if isinstance(artist, Histogram):
        labels = {
            "x": AxisSpec(label=str(artist.values.column)),
            "y": AxisSpec(label="Count"),
        }
    elif isinstance(getattr(artist, "x", None), ColumnRef):
        labels = {
            "x": AxisSpec(label=str(artist.x.column)),
            "y": AxisSpec(label=str(artist.y.column)),
        }
    dpi = 100 * scale
    width, height = PREVIEW_SIZE
    figure = Figure(
        width_mm=width / 100 * 25.4,
        height_mm=height / 100 * 25.4,
        dpi=dpi,
        font_size=7,
        axes=[Axes(artists=[artist], **labels)],
    )
    canvas = FigureCanvasAgg(render(figure, data))
    canvas.draw()
    pixels = np.asarray(canvas.buffer_rgba())
    rows, cols = pixels.shape[:2]
    image = QImage(pixels.data, cols, rows, 4 * cols, QImage.Format.Format_RGBA8888)
    image = image.copy()  # own the pixels: the canvas goes away
    image.setDevicePixelRatio(scale)
    return image


def _errors_of(columns: Sequence[tuple[str, ColumnRef]]) -> dict:
    """{value column's key: error column's ref}, within each file."""
    found = {}
    for source in {ref.source for _, ref in columns}:
        refs = {str(ref.column): ref for _, ref in columns if ref.source == source}
        for error, value in error_columns(list(refs)).items():
            found[_key(refs[value])] = refs[error]
    return found


def _key(ref: ColumnRef | None) -> tuple | None:
    """A column as a dict key; a ColumnRef itself cannot be one."""
    return None if ref is None else (ref.source, ref.column)


def _kind_tile(name: str, glyph: str) -> QPushButton:
    tile = QPushButton()
    tile.setObjectName("kindTile")
    tile.setCheckable(True)
    tile.setAutoDefault(False)  # Enter adds the plot, even from a focused tile
    tile.setToolTip(name)
    column = QVBoxLayout(tile)
    column.setContentsMargins(8, 10, 8, 8)
    column.setSpacing(6)
    mark = QLabel()
    mark.setPixmap(theme.icon(glyph, theme.ACCENT, 26).pixmap(26, 26))
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    text = QLabel(name)
    text.setObjectName("tileTitle")
    text.setAlignment(Qt.AlignmentFlag.AlignCenter)
    for part in (mark, text):
        part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        column.addWidget(part)
    tile.setFixedSize(92, 74)
    return tile
