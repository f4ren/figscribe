"""Excel and LibreOffice Calc files in the window (decision 0079)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from figscribe.gui import Document, MainWindow
from figscribe.gui.sheetdialog import SheetDialog, guess_sheet
from figscribe.model import ErrorbarPlot, SheetSource
from tests.sheetfiles import Formula, write_ods, write_xlsx

nan = float("nan")

MEASURED = [
    ["Pendulum"],
    [],
    ["L", "t10", "T", "dT", "note"],
    ["m", "s", "s", "s"],
    [0.2, 8.97, Formula("B5/10", 0.897), 0.005, "ok"],
    [0.4, 12.69, Formula("B6/10", 1.269), 0.005, None],
    [0.6, 15.54, Formula("B7/10", 1.554), 0.005, "wind"],
]


@pytest.fixture
def book(tmp_path: Path) -> Path:
    path = tmp_path / "pendulum.ods"
    write_ods(path, {"about": [["Nothing but text"]], "data": MEASURED})
    return path


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    win = MainWindow(Document())
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # no dialog on closing
    win.new_from_template("single")
    win.show_error = lambda title, error: pytest.fail(f"{title}: {error}")
    return win


def _dialog(qtbot, path: Path) -> SheetDialog:
    dialog = SheetDialog(path, path.parent)
    qtbot.addWidget(dialog)
    return dialog


def _ok(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        ([["t", "U"], [1.0, 2.0]], (0, 0, ".")),
        ([["Title"], ["", ""], ["t", "U"], ["s", "V"], [1.0, 2.0]], (2, 1, ".")),
        ([["Title"], ["t", "U"], [1.0, 2.0]], (1, 0, ".")),
        ([["t", "U"], ["", ""], [1.0, 2.0]], (0, 1, ".")),
        ([[1.0, 2.0], [3.0, 4.0]], (None, 0, ".")),
        ([["t"], [1.0], [2.0]], (0, 0, ".")),
        ([["t", "U"], ["1,5", "2,5"], ["2,0", "3"]], (0, 0, ",")),
        ([["only", "text"]], (0, 0, ".")),
    ],
)
def test_how_a_sheet_is_first_read(cells, expected) -> None:
    options = guess_sheet(cells)
    assert (options["header_row"], options["skip_rows"], options["decimal"]) == expected


def test_the_dialog_takes_the_sheet_with_numbers(qtbot, book: Path) -> None:
    dialog = _dialog(qtbot, book)
    assert dialog.sheet.currentText() == "data"
    assert _ok(dialog) and dialog.error.text() == ""
    source = dialog.source()
    assert (source.sheet, source.header_row, source.skip_rows) == ("data", 2, 1)
    assert source.columns == ["L", "t10", "T", "dT", "note"]
    headers = [
        dialog.table.horizontalHeaderItem(i).text()
        for i in range(dialog.table.columnCount())
    ]
    assert headers == ["L [m]", "t10 [s]", "T [s]", "dT [s]", "note"]
    assert dialog.table.item(0, 2).text() == "0.897"
    assert dialog.table.item(0, 4).text() == "ok"
    write_ods(book, {"data": [["a"], [1 / 3]]})
    assert _dialog(qtbot, book).table.item(0, 0).text() == "0.333333"
    chips = [dialog.chips.itemAt(i).widget().text() for i in range(3)]
    assert chips == ["Sheet data ▾", "Names in row 3 ▾", "Units in row 4 ▾"]


def test_columns_of_text_are_named_and_not_offered_for_plots(qtbot, book) -> None:
    dialog = _dialog(qtbot, book)
    assert "note is not numbers (cell E5: 'ok')." in dialog.status.text()
    assert all("note" not in (s.x, s.y) for s in dialog.suggestions)
    assert dialog.suggestions[0].kind in ("errorbar", "line")


def test_gaps_are_counted(qtbot, tmp_path: Path) -> None:
    write_xlsx(tmp_path / "g.xlsx", {"s": [["a", "b"], [1, 2], [2, None], [3, None]]})
    dialog = _dialog(qtbot, tmp_path / "g.xlsx")
    assert "b has 2 empty cells, which are gaps." in dialog.status.text()


def test_another_sheet_and_settings_that_do_not_work(qtbot, book: Path) -> None:
    dialog = _dialog(qtbot, book)
    dialog.sheet.setCurrentText("about")
    assert not _ok(dialog) and "no rows of data" in dialog.error.text()
    assert dialog.source() is None and not dialog.settings.isHidden()
    dialog.sheet.setCurrentText("data")
    assert _ok(dialog) and dialog.source().sheet == "data"
    dialog.header_row.setValue(40)
    assert not _ok(dialog) and "no row 41" in dialog.error.text()


def test_importing_a_sheet_adds_the_data_and_the_plot(window, book: Path) -> None:
    shown = []

    def run(dialog: QDialog) -> bool:
        shown.append(dialog)
        return True

    window.run_dialog = run
    assert window.import_csv(book)
    assert isinstance(shown[0], SheetDialog)
    document = window.document
    (source,) = document.project.sources
    assert isinstance(source, SheetSource)
    (panel,) = document.figure.axes
    (plot,) = panel.artists
    assert isinstance(plot, ErrorbarPlot) is (
        shown[0].suggestions[0].kind == "errorbar"
    )
    assert (panel.x.label, panel.x.unit) == ("L", "m")
    np.testing.assert_array_equal(document.data(plot.x), [0.2, 0.4, 0.6])
    document.undo()
    assert document.project.sources == []


def test_dropped_spreadsheets_are_added(window, book: Path) -> None:
    window.run_dialog = lambda dialog: True
    window.open_dropped([book])
    assert [type(s) for s in window.document.project.sources] == [SheetSource]


def _imported(window: MainWindow, path: Path) -> SheetSource:
    window.run_dialog = lambda dialog: True
    assert window.import_csv(path)
    return window.document.project.sources[0]


def test_the_panel_offers_the_sheets_and_reads_the_other(window, tmp_path) -> None:
    path = tmp_path / "two.xlsx"
    write_xlsx(path, {"a": [["t", "U"], [1, 2]], "b": [["t", "U"], [1, 9], [2, 8]]})
    source = _imported(window, path)
    window.document.select(source.id)
    properties = window.properties
    sheet = properties.editors[("sheet",)].widget
    assert [sheet.itemText(i) for i in range(sheet.count())] == ["a", "b"]
    sheet.setCurrentText("b")
    sheet.activated.emit(sheet.currentIndex())
    changed = window.document.project.sources[0]
    assert (changed.sheet, changed.row_count) == ("b", 2)


def test_another_file_asks_which_sheet(window, book: Path, tmp_path: Path) -> None:
    source = _imported(window, book)
    other = tmp_path / "next.xlsx"
    write_xlsx(other, {"x": MEASURED, "y": [["nothing"], [1]]})
    window.choose_data_file = lambda s: other
    asked = []
    window.choose_sheet = lambda old, names: asked.append((old, names)) or "x"
    window.use_another_file(source.id)
    assert asked == [("data", ["x", "y"])]
    assert window.document.project.sources[0].sheet == "x"
    assert window.document.project.sources[0].format == "xlsx"


def test_another_file_is_left_when_no_sheet_is_chosen(window, book, tmp_path) -> None:
    source = _imported(window, book)
    other = tmp_path / "next.xlsx"
    write_xlsx(other, {"x": MEASURED, "y": MEASURED})
    window.choose_data_file = lambda s: other
    window.choose_sheet = lambda old, names: None
    window.use_another_file(source.id)
    assert window.document.project.sources[0].path.endswith("pendulum.ods")
