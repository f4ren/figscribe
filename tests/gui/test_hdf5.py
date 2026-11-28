"""HDF5 files in the window (decision 0081)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import h5py
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox

from figscribe.gui import Document, MainWindow
from figscribe.gui.hdf5dialog import Hdf5Dialog
from figscribe.model import Hdf5Source, ImagePlot, LinePlot
from figscribe.tools.workspace import array_choices, column_choices
from tests.hdf5files import write_h5, write_scan


@pytest.fixture
def scan(tmp_path: Path) -> Path:
    return write_scan(tmp_path / "scan.h5")


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    win = MainWindow(Document())
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # no dialog on closing
    win.new_from_template("single")
    win.show_error = lambda title, error: pytest.fail(f"{title}: {error}")
    return win


def _dialog(qtbot, path: Path) -> Hdf5Dialog:
    dialog = Hdf5Dialog(path, path.parent)
    qtbot.addWidget(dialog)
    return dialog


def _ok(dialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def _headers(dialog) -> list[str]:
    return [
        dialog.table.horizontalHeaderItem(i).text()
        for i in range(dialog.table.columnCount())
    ]


def test_the_dialog_takes_the_first_table_and_shows_the_tree(qtbot, scan) -> None:
    dialog = _dialog(qtbot, scan)
    assert not dialog.settings.isHidden()
    items = dialog.items
    assert list(items)[:2] == ["/", "/image"]
    assert items["/run1/U"].parent() is items["/run1"]
    assert items["/run1"].text(1) == "3 columns"
    assert items["/image"].text(1) == "3 × 4 numbers"
    assert items["/run1/gain"].text(1) == "it holds one value only"
    assert not items["/run1/gain"].flags() & Qt.ItemFlag.ItemIsSelectable
    assert dialog.tree.currentItem() is items["/run1"]
    assert _ok(dialog) and dialog.error.text() == ""
    source = dialog.source()
    assert (source.dataset, source.holds) == ("/run1", "group")
    assert _headers(dialog) == ["U [µV]", "counts", "t [s]"]
    assert (dialog.table.rowCount(), dialog.table.item(8, 2).text()) == (9, "4")
    assert "9 rows · 3 columns" in dialog.summary.text()
    assert "Left out: comment (it holds one value only), gain" in dialog.status.text()


def test_choosing_another_entry(qtbot, scan) -> None:
    dialog = _dialog(qtbot, scan)
    dialog.tree.setCurrentItem(dialog.items["/table"])
    assert dialog.source().holds == "table"
    assert _headers(dialog) == ["f", "n"]
    assert "name (it holds text)" in dialog.status.text()
    dialog.tree.setCurrentItem(dialog.items["/run1/counts"])
    assert dialog.source().columns == ["counts"]
    assert dialog.suggestions[0].kind == "histogram"


def test_an_image_is_offered_for_two_dimensions(qtbot, scan) -> None:
    dialog = _dialog(qtbot, scan)
    dialog.tree.setCurrentItem(dialog.items["/image"])
    assert dialog.table.columnCount() == 4
    (suggestion,) = dialog.suggestions
    assert (suggestion.kind, suggestion.title) == ("image", "Image of image")
    artist = dialog.planned_artist()
    assert isinstance(artist, ImagePlot) and artist.colorbar is not None


def test_a_big_image_shows_only_its_start(qtbot, tmp_path: Path) -> None:
    path = write_h5(tmp_path / "big.h5", {"m": np.zeros((100, 2000))})
    dialog = _dialog(qtbot, path)
    assert (dialog.table.rowCount(), dialog.table.columnCount()) == (20, 50)
    assert "100 rows · 2000 columns" in dialog.summary.text()


def test_columns_of_different_lengths(qtbot, tmp_path: Path) -> None:
    path = write_h5(
        tmp_path / "m.h5",
        {
            "a_time": np.arange(8.0),
            "b_volt": np.arange(8.0),
            "freq": np.arange(5.0),
            "psd": np.arange(5.0),
        },
    )
    dialog = _dialog(qtbot, path)
    assert (
        dialog.table.item(7, 2).text() == "" and dialog.table.item(7, 0).text() == "7"
    )
    assert "different lengths" in dialog.status.text()
    # A first plot takes only columns that go together.
    assert {(s.x, s.y) for s in dialog.suggestions} == {("a_time", "b_volt")}


def test_importing_adds_the_data_and_the_plot(window, scan: Path) -> None:
    shown = []

    def run(dialog: QDialog) -> bool:
        shown.append(dialog)
        return True

    window.run_dialog = run
    assert window.import_csv(scan)
    assert isinstance(shown[0], Hdf5Dialog)
    document = window.document
    (source,) = document.project.sources
    assert isinstance(source, Hdf5Source)
    (panel,) = document.figure.axes
    (plot,) = panel.artists
    assert isinstance(plot, LinePlot)
    assert (panel.x.label, panel.x.unit) == ("t", "s")
    assert (panel.y.label, panel.y.unit) == ("U", "µV")
    document.undo()
    assert document.project.sources == []


def test_dropped_files_are_added(window, scan: Path) -> None:
    window.run_dialog = lambda dialog: True
    window.open_dropped([scan])
    assert [type(s) for s in window.document.project.sources] == [Hdf5Source]


def test_a_file_that_cannot_be_read_is_told(window, tmp_path: Path) -> None:
    path = tmp_path / "bad.h5"
    path.write_text("no")
    told = []
    window.show_error = lambda title, error: told.append(str(error))
    assert not window.import_csv(path)
    assert "cannot read bad.h5" in told[0]


def _imported(window: MainWindow, path: Path) -> Hdf5Source:
    window.run_dialog = lambda dialog: True
    assert window.import_csv(path)
    return window.document.project.sources[0]


def test_the_panel_offers_the_datasets_and_reads_another(window, scan) -> None:
    source = _imported(window, scan)
    window.document.select(source.id)
    dataset = window.properties.editors[("dataset",)].widget
    offered = [dataset.itemText(i) for i in range(dataset.count())]
    assert offered[:2] == ["/image", "/run1"]  # not "/", which holds no columns
    dataset.setCurrentText("/table")
    dataset.activated.emit(dataset.currentIndex())
    changed = window.document.project.sources[0]
    assert (changed.dataset, changed.holds, changed.row_count) == (
        "/table",
        "table",
        4,
    )


def test_another_file_asks_which_dataset(window, scan, tmp_path: Path) -> None:
    source = _imported(window, scan)
    other = write_h5(
        tmp_path / "next.h5",
        {
            f"{run}/{name}": np.arange(3.0)
            for run in ("a", "b")
            for name in ("U", "counts", "t")
        },
    )
    window.choose_data_file = lambda s: other
    asked = []
    window.choose_dataset = lambda old, paths: asked.append((old, paths)) or "/b"
    window.use_another_file(source.id)
    assert [old for old, _ in asked] == ["/run1"]
    assert window.document.project.sources[0].dataset == "/b"


def test_what_changed_is_shown_for_a_renamed_group(window, tmp_path: Path) -> None:
    path = write_h5(tmp_path / "r.h5", {"run1/t": [1.0, 2], "run1/U": [2.0, 3]})
    source = _imported(window, path)
    write_h5(path, {"run2/t": [1.0, 2], "run2/U": [2.0, 3]})
    shown = []
    window.data_bar.show_message = lambda title, text: shown.append(text)
    window.data_bar._show_change(source)
    assert "dataset is now '/run2'" in shown[0]


def test_groups_of_one_file_are_told_apart_in_the_lists(window, scan) -> None:
    _imported(window, scan)

    def run(dialog) -> bool:
        dialog.tree.setCurrentItem(dialog.items["/table"])
        return True

    window.run_dialog = run
    assert window.import_csv(scan)
    project = window.document.project
    names = [name for name, _ in column_choices(project, window.document.data)]
    assert "scan.h5[/run1]: U" in names and "scan.h5[/table]: f" in names
    assert [name for name, _ in array_choices(project)] == [
        "scan.h5[/run1] (whole table)",
        "scan.h5[/table] (whole table)",
    ]


def test_the_data_summary_and_outline_show_the_source(window, scan) -> None:
    source = _imported(window, scan)
    window.outline.rebuild()
    item = window.outline.findItems(
        "scan.h5", Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive
    )
    assert item and item[0].text(1) == "3 columns"
    assert source.row_count == 9


def test_a_two_dimensional_dataset_is_shown_as_an_image(window, tmp_path) -> None:
    path = tmp_path / "map.h5"
    with h5py.File(path, "w") as file:
        file["m"] = np.arange(12.0).reshape(3, 4)
    source = _imported(window, path)
    (plot,) = window.document.figure.axes[0].artists
    assert isinstance(plot, ImagePlot) and plot.data.source == source.id
    window.outline.rebuild()


@pytest.mark.parametrize(
    ("columns", "x"),
    [
        # A name that says it is what the others are measured against.
        ({"U": [1.0, 2, 3], "t": [3.0, 1, 2]}, "t"),
        ({"A": [1.0, 2, 3], "Time_s": [3.0, 1, 2]}, "Time_s"),
        ({"psd": [3.0, 1, 2], "frequency": [1.0, 2, 3]}, "frequency"),
        # Else the first column that only rises.
        ({"a": [3.0, 1, 2], "b": [1.0, 2, 3]}, "b"),
        # Else the first.
        ({"a": [3.0, 1, 2], "b": [1.0, 3, 2]}, "a"),
    ],
)
def test_what_a_first_plot_has_as_x(qtbot, tmp_path: Path, columns, x: str) -> None:
    path = write_h5(tmp_path / "m.h5", columns)
    dialog = _dialog(qtbot, path)
    assert dialog.suggestions[0].x == x


def test_no_row_of_detected_settings(qtbot, scan: Path) -> None:
    dialog = _dialog(qtbot, scan)
    assert dialog.detected.isHidden() and dialog.chips.count() == 0


@pytest.mark.parametrize("kind", ["group", "table"])
def test_more_columns_than_the_preview_shows(qtbot, tmp_path: Path, kind) -> None:
    names = [f"c{i:02}" for i in range(60)]
    if kind == "group":
        data = {f"g/{name}": np.arange(3.0) + i for i, name in enumerate(names)}
    else:
        table = np.zeros(3, dtype=[(name, "f8") for name in names])
        data = {"g": table}
    dialog = _dialog(qtbot, write_h5(tmp_path / "wide.h5", data))
    assert _ok(dialog) and dialog.error.text() == ""
    assert dialog.source().columns == names
    assert dialog.table.columnCount() == 50
    assert _headers(dialog)[:2] == ["c00", "c01"]
    assert "3 rows · 60 columns" in dialog.summary.text()


def test_the_source_records_the_file_the_preview_shows(qtbot, scan) -> None:
    before = hashlib.sha256(scan.read_bytes()).hexdigest()
    dialog = _dialog(qtbot, scan)
    write_h5(scan, {"table": [1.0, 2]})  # rewritten while the dialog is open
    dialog.tree.setCurrentItem(dialog.items["/run1/counts"])
    assert dialog.source().sha256 == before
