"""The dialog that adds a plot: kinds as tiles, columns as a sentence, only
the fields that apply, a live preview, and where the plot goes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from figscribe.gui import Document, MainWindow
from figscribe.gui.plotdialog import NEW_PANEL, PlotDialog
from figscribe.model import (
    ArrayRef,
    ColorMesh,
    ColumnRef,
    ErrorbarPlot,
    Histogram,
    ImagePlot,
    LinePlot,
    ScatterPlot,
)

NAMES = ("t", "U", "dU", "T", "dT")
COLUMNS = [(f"scan.csv: {c}", ColumnRef(source="src", column=c)) for c in NAMES]
VALUES = {
    "t": np.linspace(0.0, 10.0, 21),
    "U": np.exp(-((np.linspace(0.0, 10.0, 21) - 5.0) ** 2) / 4.0),
    "dU": np.full(21, 0.05),
    "T": np.linspace(290.0, 300.0, 21),
    "dT": np.full(21, 0.5),
}


def _data(ref):
    if isinstance(ref, ArrayRef):
        return np.arange(12.0).reshape(3, 4)
    return VALUES[ref.column]


@pytest.fixture
def dialog(qtbot) -> PlotDialog:
    widget = PlotDialog(COLUMNS, data=_data, summary="scan.csv · 21 rows")
    qtbot.addWidget(widget)
    return widget


def _shown(dialog: PlotDialog, widget) -> bool:
    return widget.isVisibleTo(dialog)


def _choose(box, text: str) -> None:
    index = box.findText(text)
    assert index >= 0, [box.itemText(i) for i in range(box.count())]
    box.setCurrentIndex(index)
    box.activated.emit(index)


def test_the_kinds_are_tiles_and_those_without_data_say_why(dialog) -> None:
    assert list(dialog.tiles) == [
        "Line",
        "Points",
        "Error bars",
        "Histogram",
        "Image",
        "Color mesh",
    ]
    image = dialog.tiles["Image"]
    assert not image.isEnabled() and ".npy" in image.toolTip()
    dialog.tiles["Points"].click()
    assert isinstance(dialog.artist(), ScatterPlot)


def test_a_column_named_as_an_error_starts_error_bars(dialog) -> None:
    assert dialog.tiles["Error bars"].isChecked()
    artist = dialog.artist()
    assert isinstance(artist, ErrorbarPlot)
    assert (artist.x.column, artist.y.column, artist.yerr.column) == ("t", "U", "dU")
    assert artist.xerr is None and artist.label == "U"
    assert "dU looks like the error of U" in dialog.hint.text()


def test_one_file_shows_its_columns_by_name(dialog) -> None:
    assert [dialog.y.itemText(i) for i in range(dialog.y.count())] == list(NAMES)
    assert dialog.summary.text() == "scan.csv · 21 rows"


def test_choosing_y_brings_its_error_and_its_label(dialog) -> None:
    _choose(dialog.y, "T")
    assert dialog.yerr.currentText() == "dT"
    assert dialog.label.text() == "T"


def test_only_the_fields_that_apply_are_shown(dialog) -> None:
    dialog.tiles["Line"].click()
    assert not _shown(dialog, dialog.yerr) and not _shown(dialog, dialog.array)
    assert _shown(dialog, dialog.x) and dialog.hint.text() == ""
    assert isinstance(dialog.artist(), LinePlot)

    dialog.tiles["Histogram"].click()
    assert not _shown(dialog, dialog.x)
    assert dialog.y_caption.text() == "Values"
    histogram = dialog.artist()
    assert isinstance(histogram, Histogram) and histogram.values.column == "U"


def test_two_d_data_is_plotted_as_an_image_or_a_mesh(qtbot) -> None:
    ref = ArrayRef(source="s")
    dialog = PlotDialog([], arrays=[("map.npy", ref)], data=_data)
    qtbot.addWidget(dialog)
    assert dialog.tiles["Image"].isChecked()  # the only kind with data
    assert not dialog.tiles["Line"].isEnabled()
    assert _shown(dialog, dialog.array) and not _shown(dialog, dialog.y)
    image = dialog.artist()
    assert isinstance(image, ImagePlot) and image.data == ref
    assert image.colorbar is not None
    dialog.tiles["Color mesh"].click()
    mesh = dialog.artist()
    assert isinstance(mesh, ColorMesh) and mesh.c == ref and mesh.x is None


def test_the_preview_draws_what_is_chosen(dialog) -> None:
    first = dialog.preview.pixmap().toImage()
    assert not first.isNull()
    dialog.tiles["Histogram"].click()
    assert dialog.preview.pixmap().toImage() != first


def test_a_preview_that_cannot_be_drawn_says_why(qtbot) -> None:
    def broken(ref):
        raise ValueError("cannot be read")

    dialog = PlotDialog(COLUMNS, data=broken)
    qtbot.addWidget(dialog)
    assert dialog.preview.pixmap().isNull()
    assert dialog.preview.text()


def test_enter_adds_the_plot(dialog) -> None:
    assert dialog.add.text() == "Add plot" and dialog.add.isDefault()
    dialog.show()
    dialog.tiles["Points"].setFocus()
    QTest.keyClick(dialog.tiles["Points"], Qt.Key.Key_Return)
    assert dialog.result() == PlotDialog.DialogCode.Accepted


# --- in the main window ------------------------------------------------------


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = MainWindow(Document.open(example))
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    return win


def test_the_dialog_says_where_the_plot_goes(window: MainWindow) -> None:
    seen = {}

    def look(dialog: PlotDialog) -> bool:
        seen["targets"] = [
            dialog.target.itemText(i) for i in range(dialog.target.count())
        ]
        seen["summary"] = dialog.summary.text()
        dialog.tiles["Line"].click()
        return True

    window.run_dialog = look
    window.add_plot()
    assert seen["targets"] == ["Panel A", "A new panel to the right"]
    assert seen["summary"] == "scan.csv · 41 rows"
    assert isinstance(window.document.figure.axes[0].artists[-1], LinePlot)


def test_a_plot_in_a_new_panel_is_one_step(window: MainWindow) -> None:
    def new_panel(dialog: PlotDialog) -> bool:
        dialog.target.setCurrentIndex(dialog.target.findData(NEW_PANEL))
        dialog.tiles["Points"].click()
        return True

    window.run_dialog = new_panel
    window.add_plot()
    figure = window.document.figure
    assert len(figure.axes) == 2 and figure.layout.cols == 2
    new = figure.axes[1]
    assert [a.kind for a in new.artists] == ["scatter"]
    assert (new.x.label, new.y.label) == ("t", "U")  # named after the columns
    assert window.document.selected == new.artists[0].id
    window.document.undo()
    assert len(window.document.figure.axes) == 1
