"""Importing data and adding plots: from a new project to a drawn figure."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QDialogButtonBox

from figscribe.gui import Document, MainWindow
from figscribe.gui.importdialog import ImportDialog, guess_options
from figscribe.gui.plotdialog import PlotDialog
from figscribe.model import ColumnRef, ErrorbarPlot, LinePlot, ScatterPlot


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "t,U\n0,1.5\n1,2.5\n",
            {"delimiter": ",", "decimal": ".", "header_row": 0, "skip_rows": 0},
        ),
        (
            "# scan\nt,U,dU\ns,V,V\n0.0,1.0,0.1\n0.5,1.2,0.1\n",
            {"delimiter": ",", "decimal": ".", "header_row": 1, "skip_rows": 1},
        ),
        (
            "Zeit;Spannung\n0,5;1,25\n1,0;2,5\n",
            {"delimiter": ";", "decimal": ",", "header_row": 0, "skip_rows": 0},
        ),
        (
            "x\ty\n1\t2\n3\t4\n",
            {"delimiter": "\t", "decimal": ".", "header_row": 0, "skip_rows": 0},
        ),
        (
            "# no header\n1.0  2.0\n3.0  4.0\n",
            {"delimiter": None, "decimal": ".", "header_row": None, "skip_rows": 0},
        ),
        (
            "a,b,c\n1,2\n3,4\n",
            {"delimiter": ",", "decimal": ".", "header_row": 0, "skip_rows": 0},
        ),
    ],
    ids=[
        "plain",
        "comment-and-units",
        "semicolon-decimal-comma",
        "tab",
        "whitespace",
        "header-wider-than-data",
    ],
)
def test_guess_options(text: str, expected: dict) -> None:
    options = guess_options(text)
    assert {k: options[k] for k in expected} == expected


def _ok(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_the_dialog_previews_the_guessed_reading(qtbot, example: Path) -> None:
    dialog = ImportDialog(example.parent / "scan.csv", example.parent)
    qtbot.addWidget(dialog)
    assert _ok(dialog) and dialog.error.text() == ""
    headers = [
        dialog.table.horizontalHeaderItem(i).text()
        for i in range(dialog.table.columnCount())
    ]
    assert headers == ["t [s]", "U [V]", "dU [V]"]
    assert dialog.table.item(1, 0).text() == "0.25"

    source = dialog.source()
    assert source.path == "scan.csv"
    assert (source.header_row, source.skip_rows) == (1, 1)
    assert source.columns == ["t", "U", "dU"]


def test_the_dialog_says_what_it_detected(qtbot, example: Path) -> None:
    dialog = ImportDialog(example.parent / "scan.csv", example.parent)
    qtbot.addWidget(dialog)
    chips = [dialog.chips.itemAt(i).widget().text() for i in range(5)]
    assert chips == [
        "Comma-separated ▾",
        "Decimal point ▾",
        "Names in line 2 ▾",
        "Units in line 3 ▾",
        "# comments ▾",
    ]
    assert dialog.chips.count() == 5
    assert dialog.summary.text().startswith("41 rows · 3 columns")
    assert "dU looks like the error of U." in dialog.status.text()
    assert dialog.units == ["s", "V", "V"]
    assert dialog.unit_of("U") == "V" and dialog.unit_of("nope") is None
    assert dialog.header_row.text() == "2"  # lines are counted from 1 on screen

    assert dialog.settings.isHidden()
    dialog.chips.itemAt(0).widget().click()
    assert not dialog.settings.isHidden()


def test_the_dialog_suggests_first_plots(qtbot, example: Path) -> None:
    dialog = ImportDialog(example.parent / "scan.csv", example.parent)
    qtbot.addWidget(dialog)
    assert [s.title for s in dialog.suggestions] == [
        "U ± dU against t",
        "U against t",
        "U against t",
    ]
    assert dialog.suggestion.kind == "errorbar"
    artist = dialog.planned_artist()
    assert isinstance(artist, ErrorbarPlot)
    assert artist.yerr == ColumnRef(source=dialog.source().id, column="dU")

    dialog.choose(1)
    dialog.skip_rows.setValue(0)  # the units line is now read as data: refused
    assert dialog.planned_artist() is None
    assert not dialog.settings.isHidden()
    dialog.skip_rows.setValue(1)
    assert dialog.suggestion.kind == "line"  # the choice survives


def test_a_single_column_suggests_a_histogram(qtbot, tmp_path: Path) -> None:
    single = tmp_path / "single.csv"
    single.write_text("counts\n1\n2\n3\n", encoding="utf-8")
    dialog = ImportDialog(single, tmp_path)
    qtbot.addWidget(dialog)
    assert [s.kind for s in dialog.suggestions] == ["histogram"]
    assert dialog.mode == "plot"
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.text() == "Add and plot"


def test_a_histogram_on_import_names_its_axes(window, tmp_path: Path) -> None:
    single = tmp_path / "single.csv"
    single.write_text("counts\n1\n2\n3\n", encoding="utf-8")
    window.import_csv(single)
    axes = window.document.figure.axes[0]
    assert axes.artists[0].kind == "histogram"
    assert (axes.x.label, axes.y.label) == ("counts", "Count")
    assert window.preview.error is None


def test_a_wrong_option_disables_ok(qtbot, example: Path) -> None:
    dialog = ImportDialog(example.parent / "scan.csv", example.parent)
    qtbot.addWidget(dialog)
    dialog.skip_rows.setValue(0)  # the line of units is not numbers
    assert not _ok(dialog) and dialog.source() is None
    assert "scan.csv" in dialog.error.text()
    dialog.skip_rows.setValue(1)
    assert _ok(dialog)


def test_a_header_wider_than_the_data_is_refused(qtbot, tmp_path: Path) -> None:
    csv = tmp_path / "data.csv"
    csv.write_text("a,b,c\n1,2\n3,4\n", encoding="utf-8")
    dialog = ImportDialog(csv, tmp_path)
    qtbot.addWidget(dialog)
    assert not _ok(dialog)
    assert "3 columns" in dialog.error.text()


def test_an_unsaved_project_stores_the_absolute_path(qtbot, example: Path) -> None:
    csv = example.parent / "scan.csv"
    dialog = ImportDialog(csv, None)
    qtbot.addWidget(dialog)
    assert Path(dialog.source().path) == csv.resolve()


def test_a_file_without_header_is_read_by_column_number(qtbot, tmp_path: Path) -> None:
    dat = tmp_path / "data.dat"
    dat.write_text("1.0 2.0 3.0\n4.0 5.0 6.0\n", encoding="utf-8")
    dialog = ImportDialog(dat, tmp_path)
    qtbot.addWidget(dialog)
    assert dialog.source().header_row is None
    assert dialog.table.horizontalHeaderItem(2).text() == "2"


# --- the plot dialog ---------------------------------------------------------


COLUMNS = [
    (f"scan.csv: {c}", ColumnRef(source="src", column=c)) for c in ("t", "U", "dU")
]


def test_the_plot_dialog_starts_with_the_first_two_columns(qtbot) -> None:
    dialog = PlotDialog(COLUMNS)
    qtbot.addWidget(dialog)
    artist = dialog.artist()
    assert isinstance(artist, LinePlot)
    assert (artist.x.column, artist.y.column, artist.label) == ("t", "U", "U")
    assert not dialog.yerr.isEnabled()


def test_error_bars_take_their_columns(qtbot) -> None:
    dialog = PlotDialog(COLUMNS)
    qtbot.addWidget(dialog)
    dialog.kind.setCurrentText("Error bars")
    assert dialog.yerr.isEnabled()
    dialog.yerr.setCurrentIndex(3)  # (none), t, U, dU
    dialog.label.setText("")
    artist = dialog.artist()
    assert isinstance(artist, ErrorbarPlot)
    assert artist.yerr.column == "dU" and artist.xerr is None
    assert artist.label is None

    dialog.kind.setCurrentText("Scatter")
    assert isinstance(dialog.artist(), ScatterPlot)


# --- in the main window ------------------------------------------------------


@pytest.fixture
def window(qtbot) -> MainWindow:
    win = MainWindow(Document())
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.run_dialog = lambda dialog: True  # accept as proposed
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    return win


def _only_data(dialog) -> bool:
    """Import without a plot; accept any later dialog as proposed."""
    if not isinstance(dialog, ImportDialog):
        return True
    dialog.data_only.click()
    return dialog.result() == ImportDialog.DialogCode.Accepted


def test_from_a_new_project_to_a_drawn_plot(window: MainWindow, example: Path) -> None:
    window.run_dialog = _only_data
    window.import_csv(example.parent / "scan.csv")
    source = window.document.project.sources[0]
    assert window.document.selected == source.id
    assert window.document.history.undo_text == "Add csv source"

    window.add_plot()
    figure = window.document.figure
    assert len(figure.axes) == 1
    artist = figure.axes[0].artists[0]
    assert isinstance(artist, LinePlot)
    assert window.document.selected == artist.id
    assert window.preview.error is None
    np.testing.assert_allclose(window.document.data(artist.x)[:2], [0.0, 0.25])

    # Axes and plot came as one step.
    window.document.undo()
    assert window.document.figure.axes == []


def test_a_second_plot_goes_into_the_selected_axes(window, example: Path) -> None:
    window.run_dialog = _only_data
    window.import_csv(example.parent / "scan.csv")
    window.add_plot()
    first = window.document.figure.axes[0].artists[0]
    window.document.select(first.id)
    window.add_plot()
    assert len(window.document.figure.axes) == 1
    assert len(window.document.figure.axes[0].artists) == 2
    assert window.document.history.undo_text == "Add line plot"


def test_add_and_plot_is_one_step(window: MainWindow, example: Path) -> None:
    window.import_csv(example.parent / "scan.csv")  # accepted as proposed
    axes = window.document.figure.axes[0]
    artist = axes.artists[0]
    assert isinstance(artist, ErrorbarPlot)
    assert (artist.x.column, artist.y.column, artist.yerr.column) == ("t", "U", "dU")
    assert (axes.x.label, axes.x.unit) == ("t", "s")
    assert (axes.y.label, axes.y.unit) == ("U", "V")
    assert window.document.selected == artist.id
    assert window.document.history.undo_text == "Add scan.csv and plot"
    assert window.preview.error is None
    window.document.undo()
    assert window.document.project.sources == []
    assert window.document.figure.axes == []


def test_plotting_into_an_empty_panel_names_its_axes(window, example: Path) -> None:
    window.new_from_template("single")
    window.import_csv(example.parent / "scan.csv")
    axes = window.document.figure.axes[0]
    assert len(window.document.figure.axes) == 1
    assert (axes.x.label, axes.y.unit) == ("t", "V")
    window.document.undo()
    assert window.document.figure.axes[0].x.label is None


def test_a_chosen_suggestion_is_plotted(window: MainWindow, example: Path) -> None:
    def points(dialog: ImportDialog) -> bool:
        dialog.choose(2)
        assert dialog.suggestion.kind == "scatter"
        return True

    window.run_dialog = points
    window.import_csv(example.parent / "scan.csv")
    assert isinstance(window.document.figure.axes[0].artists[0], ScatterPlot)


def test_choosing_columns_opens_the_plot_dialog(window, example: Path) -> None:
    def custom(dialog) -> bool:
        if isinstance(dialog, ImportDialog):
            dialog.custom.click()
            return dialog.result() == ImportDialog.DialogCode.Accepted
        assert isinstance(dialog, PlotDialog)
        return True

    window.run_dialog = custom
    window.import_csv(example.parent / "scan.csv")
    assert len(window.document.project.sources) == 1
    assert isinstance(window.document.figure.axes[0].artists[0], LinePlot)


def test_adding_a_plot_without_data_explains_why(window: MainWindow) -> None:
    window.add_plot()
    assert window.errors and "Import" in window.errors[0][1]
    assert not window.document.history.can_undo


def test_a_cancelled_import_changes_nothing(window, example: Path) -> None:
    window.run_dialog = lambda dialog: False
    window.import_csv(example.parent / "scan.csv")
    assert window.document.project.sources == []


def test_an_unreadable_file_is_reported(window, tmp_path: Path) -> None:
    window.import_csv(tmp_path / "missing.csv")
    assert window.errors and "missing.csv" in window.errors[0][0]


def test_numbered_columns_are_offered_for_plotting(window, tmp_path: Path) -> None:
    dat = tmp_path / "data.dat"
    dat.write_text("1.0 2.0\n3.0 4.0\n5.0 6.0\n", encoding="utf-8")
    window.import_csv(dat)
    labels = [text for text, _ in window.document.column_choices()]
    assert labels == ["data.dat: 0", "data.dat: 1"]
    window.add_plot()
    artist = window.document.figure.axes[0].artists[0]
    assert (artist.x.column, artist.y.column) == (0, 1)
    assert window.preview.error is None
