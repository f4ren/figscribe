"""Dates and times in the window (decision 0082)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from matplotlib.dates import date2num
from PySide6.QtWidgets import QDialogButtonBox

from figscribe.commands import InsertItem
from figscribe.gui import Document, MainWindow
from figscribe.gui.breaks import break_entries
from figscribe.gui.dates import date_label
from figscribe.gui.document import axis_id
from figscribe.gui.hdf5dialog import Hdf5Dialog
from figscribe.gui.importdialog import ImportDialog, guess_options
from figscribe.gui.names import artist_name
from figscribe.gui.sheetdialog import SheetDialog, guess_sheet
from figscribe.model import (
    Annotation,
    Conversion,
    ReferenceLine,
    ShadedSpan,
)
from tests.hdf5files import write_h5
from tests.sheetfiles import write_xlsx
from tests.timedata import log_file


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    win = MainWindow(Document())
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # no dialog on closing
    win.new_from_template("single")
    win.show_error = lambda title, error: pytest.fail(f"{title}: {error}")
    win.run_dialog = lambda dialog: True
    return win


def _ok(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def _row(dialog, row: int) -> list[str]:
    return [dialog.table.item(row, c).text() for c in range(dialog.table.columnCount())]


@pytest.mark.parametrize(
    "line", ["2026-11-01 22:00,20.5", "2026-11-01T22:00+01:00,20.5", "2026-11-01,1"]
)
def test_the_header_of_a_file_with_dates_is_found(line: str) -> None:
    options = guess_options(f"# log\ntime,T\n{line}\n")
    assert (options["header_row"], options["skip_rows"]) == (1, 0)


def test_the_header_of_a_sheet_with_dates_is_found() -> None:
    cells = [["title", ""], ["time", "T"], [datetime(2026, 11, 1), "x"]]
    assert guess_sheet(cells)["header_row"] == 1


def test_the_text_dialog_shows_dates_and_proposes_them_as_x(qtbot, tmp_path) -> None:
    path = tmp_path / "d.csv"
    path.write_text("T,when\n20.5,2026-11-01 22:00\n20.7,2026-11-01 22:10\n")
    dialog = ImportDialog(path, tmp_path)
    qtbot.addWidget(dialog)
    assert _ok(dialog) and dialog.error.text() == ""
    assert _row(dialog, 1) == ["20.7", "2026-11-01 22:10"]
    assert "when read as dates" in dialog.status.text()
    assert (dialog.suggestions[0].x, dialog.suggestions[0].y) == ("when", "T")
    assert [s.kind for s in dialog.suggestions] == ["line", "scatter"]


def test_dates_with_a_zone_are_told(qtbot, tmp_path: Path) -> None:
    dialog = ImportDialog(log_file(tmp_path, zone="+01:00"), tmp_path)
    qtbot.addWidget(dialog)
    assert _row(dialog, 0)[0] == "2026-11-01 22:00"
    assert "time zone is not converted" in dialog.status.text()


def test_the_preview_shows_a_column_of_dates_alike(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text("when,T\n2026-11-01 23:00,1\n2026-11-02,2\n")
    dialog = ImportDialog(path, tmp_path)
    qtbot.addWidget(dialog)
    assert _row(dialog, 1)[0] == "2026-11-02 00:00"


def test_only_dates_offer_no_plot(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text("when\n2026-11-01\n2026-11-02\n")
    dialog = ImportDialog(path, tmp_path)
    qtbot.addWidget(dialog)
    assert _ok(dialog) and dialog.suggestions == []


def test_the_sheet_dialog(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "log.xlsx"
    rows = [["T", "when"]] + [
        [20.0 + i, datetime(2026, 11, 1, 22, i)] for i in range(3)
    ]
    write_xlsx(path, {"s": rows})
    dialog = SheetDialog(path, tmp_path)
    qtbot.addWidget(dialog)
    assert _ok(dialog) and dialog.error.text() == ""
    assert (dialog.suggestions[0].x, dialog.suggestions[0].y) == ("when", "T")


def test_the_hdf5_dialog(qtbot, tmp_path: Path) -> None:
    stamps = np.array([b"2026-11-01 22:00", b"2026-11-01 22:10"])
    path = write_h5(tmp_path / "log.h5", {"run/T": [1.0, 2.0], "run/when": stamps})
    dialog = Hdf5Dialog(path, tmp_path)
    qtbot.addWidget(dialog)
    assert _ok(dialog) and dialog.error.text() == ""
    assert _row(dialog, 1) == ["2", "2026-11-01 22:10"]
    assert (dialog.suggestions[0].x, dialog.suggestions[0].y) == ("when", "T")


@pytest.mark.parametrize("kind", ["csv", "npy"])
def test_importing_a_file_with_dates(window, tmp_path: Path, kind: str) -> None:
    if kind == "csv":
        path = log_file(tmp_path)
    else:
        path = tmp_path / "t.npy"
        np.save(path, np.array(["2026-11-01", "2026-11-02"], dtype="datetime64[D]"))
    assert window.import_csv(path)
    assert window.document.project.sources[0].time_columns == [0]
    if kind == "csv":
        (plot,) = window.document.figure.axes[0].artists
        assert plot.x.column == "time" and plot.y.column == "T"
    window.outline.rebuild()


def _day(text: str) -> float:
    return float(date2num(np.datetime64(text)))


def _plot(window, tmp_path: Path, *marks):
    """The log imported and plotted, with `marks` beside the plot."""
    assert window.import_csv(log_file(tmp_path))
    panel = window.document.figure.axes[0]
    for mark in marks:
        window.document.push(InsertItem(panel.id, "artists", mark))
    return window.document.figure.axes[0].artists[0]


def _editor(window, oid: str, name: str):
    window.document.select(oid)
    return window.properties.editors[(name,)].widget


def _type(line, text: str) -> None:
    line.setText(text)
    line.editingFinished.emit()


def _panel(window):
    return window.document.figure.axes[0]


def test_the_range_of_a_date_axis_is_typed_as_dates(window, tmp_path) -> None:
    _plot(window, tmp_path)
    window.document.select(axis_id(_panel(window).id, "x"))
    form = window.properties.axis_form
    assert form.low.placeholderText().startswith("2026-11-01")
    for widget in (form.scale, form.prefix, form.number_format, form.breaks_holder):
        assert widget.isHidden()
    form.low.setText("2026-11-01 23:00")
    _type(form.high, "2026-11-02")
    assert _panel(window).x.limits == (_day("2026-11-01T23:00"), _day("2026-11-02"))
    form = window.properties.axis_form
    assert (form.low.text(), form.high.text()) == ("2026-11-01 23:00", "2026-11-02")
    # The y axis is as ever.
    window.document.select(axis_id(_panel(window).id, "y"))
    assert not window.properties.axis_form.scale.isHidden()


def test_ticks_of_a_date_axis(window, tmp_path) -> None:
    _plot(window, tmp_path)
    window.document.select(axis_id(_panel(window).id, "x"))
    form = window.properties.axis_form
    assert form.major.findData("step") == -1
    form.major.setCurrentIndex(form.major.findData("values"))
    form.major.activated.emit(form.major.currentIndex())
    _type(form.major_value, "2026-11-01 23:00, 2026-11-02")
    assert _panel(window).x.ticks == [_day("2026-11-01T23:00"), _day("2026-11-02")]
    window.document.undo()
    window.document.select(axis_id(_panel(window).id, "y"))
    window.document.select(axis_id(_panel(window).id, "x"))
    assert window.properties.axis_form.major.findData("step") == -1


def test_what_is_no_date_is_told(window, tmp_path) -> None:
    _plot(window, tmp_path)
    window.document.select(axis_id(_panel(window).id, "x"))
    form = window.properties.axis_form
    _type(form.low, "yesterday")
    assert "2026-11-01 12:30" in window.properties.error
    assert _panel(window).x.limits is None


def test_places_on_a_date_axis_are_dates(window, tmp_path) -> None:
    line = ReferenceLine(orientation="vertical", at=_day("2026-11-02"))
    span = ShadedSpan(
        orientation="vertical",
        start=_day("2026-11-01T23:00"),
        end=_day("2026-11-02T00:30"),
    )
    note = Annotation(text="n", position=(_day("2026-11-02"), 20.5))
    plot = _plot(window, tmp_path, line, span, note)
    editor = _editor(window, line.id, "at")
    assert editor.text() == "2026-11-02"
    _type(editor, "2026-11-02 01:15")
    assert _panel(window).artists[1].at == _day("2026-11-02T01:15")
    assert _editor(window, span.id, "start").text() == "2026-11-01 23:00"
    editor = _editor(window, note.id, "position")
    assert editor.text() == "2026-11-02, 20.5"
    _type(editor, "2026-11-01 23:30; 20,75")
    assert _panel(window).artists[3].position == (_day("2026-11-01T23:30"), 20.75)
    window.document.select(plot.id)
    ends = window.properties.editors[("x_range",)]
    ends.lines[0].setText("2026-11-01 23:00")
    _type(ends.lines[1], "2026-11-02")
    assert _panel(window).artists[0].x_range == (
        _day("2026-11-01T23:00"),
        _day("2026-11-02"),
    )
    assert artist_name(_panel(window).artists[1], window.document.project) == (
        "Line at x = 2026-11-02 01:15"
    )


def test_a_column_of_times_offers_the_time_since_the_start(window, tmp_path) -> None:
    plot = _plot(window, tmp_path)
    box = _editor(window, plot.id, "x_conversion")
    offered = [box.itemText(i) for i in range(box.count())]
    assert offered[:3] == [
        "as dates",
        "s since the start",
        "min since the start",
    ]
    assert box.currentText() == "as dates"
    box.setCurrentIndex(offered.index("h since the start"))
    box.activated.emit(box.currentIndex())
    shown = _panel(window).artists[0].x_conversion
    assert shown == Conversion(factor=1 / 3600, from_start=True, unit="h")
    window.document.select(_panel(window).artists[0].id)
    assert ("x_conversion", "from_start") not in window.properties.editors
    assert _editor(window, plot.id, "x_conversion").currentText() == (
        "h since the start"
    )
    # The other axis holds numbers and offers what it did.
    box = window.properties.editors[("y_conversion",)].widget
    assert box.itemText(0) == "as in the file"


def test_no_breaks_are_offered_for_dates(window, tmp_path) -> None:
    _plot(window, tmp_path)
    entries = break_entries(window.document, _panel(window).id)
    assert not any("x axis" in text for text, _, _ in entries)


def test_a_fit_to_dates_is_told_before_the_dialog(window, tmp_path) -> None:
    plot = _plot(window, tmp_path)
    window.document.select(plot.id)
    told = []
    window.show_error = lambda title, error: told.append(str(error))
    window.run_dialog = lambda dialog: pytest.fail("no dialog")
    window.add_fit()
    assert "there is no fit to dates" in told[0]


def test_a_place_anywhere_is_shown_to_a_millisecond() -> None:
    assert date_label(_day("2026-11-01T20:15") + 1.234567 / 86400) == (
        "2026-11-01 20:15:01.235"
    )
