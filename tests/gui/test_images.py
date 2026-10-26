"""2-D data in the GUI: NumPy import, images and colour meshes, colour bars."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from figscribe.commands import SetField
from figscribe.gui import Document, MainWindow
from figscribe.gui.preview import Preview
from figscribe.gui.properties import PropertyPanel
from figscribe.model import ArrayRef, ColorMesh, ImagePlot


@pytest.fixture
def window(qtbot) -> MainWindow:
    win = MainWindow(Document())
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.run_dialog = lambda dialog: True
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    return win


@pytest.fixture
def grid(tmp_path: Path) -> Path:
    y, x = np.mgrid[0:20, 0:30]
    path = tmp_path / "map.npz"
    np.savez(
        path, t=np.arange(5.0), counts=np.exp(-((x - 15) ** 2 + (y - 10) ** 2) / 40)
    )
    return path


def _artists(window: MainWindow):
    return [a for ax in window.document.figure.axes for a in ax.artists]


def test_a_2d_array_is_imported_as_an_image(window: MainWindow, grid: Path) -> None:
    assert window.import_csv(grid)  # the data action takes NumPy files too
    source = window.document.project.sources[0]
    assert source.array == "counts"  # the first 2-D array, not the first one
    [image] = _artists(window)
    assert isinstance(image, ImagePlot) and image.colorbar is not None
    assert image.data == ArrayRef(source=source.id)
    assert window.document.selected == image.id
    assert window.document.history.undo_text == "Add map.npz as an image"
    window.document.undo()
    assert not window.document.project.sources and not _artists(window)


def test_a_1d_array_is_only_added(window: MainWindow, tmp_path: Path) -> None:
    np.save(tmp_path / "t.npy", np.arange(4.0))
    assert window.import_numpy(tmp_path / "t.npy")
    assert len(window.document.project.sources) == 1 and not _artists(window)


def test_an_unreadable_file_is_reported(window: MainWindow, tmp_path: Path) -> None:
    np.save(tmp_path / "cube.npy", np.zeros((2, 2, 2)))
    assert not window.import_numpy(tmp_path / "cube.npy")
    assert "3-D" in window.errors[0][1]
    assert not window.document.project.sources


def test_add_plot_draws_an_image(window: MainWindow, grid: Path) -> None:
    window.import_numpy(grid)
    image = _artists(window)[0]
    window.document.select(image.id)

    def mesh(dialog) -> bool:
        dialog.tiles["Color mesh"].click()
        return True

    window.run_dialog = mesh
    window.add_plot()
    assert isinstance(_artists(window)[-1], ColorMesh)
    assert not window.errors


@pytest.fixture
def panel(qtbot, window: MainWindow, grid: Path) -> PropertyPanel:
    window.import_numpy(grid)
    widget = PropertyPanel(window.document)
    qtbot.addWidget(widget)
    return widget


def test_the_color_bar_can_be_switched_off_and_on(panel, window) -> None:
    document = window.document
    image = _artists(window)[0]
    document.select(image.id)
    assert "Color bar" in panel.sections
    switch = panel.editors[("colorbar",)].widget
    assert switch.isChecked()
    switch.click()  # as a person does: the box is replaced while it handles the click
    assert _artists(window)[0].colorbar is None
    assert document.history.undo_text == "Remove the color bar"
    assert "Color bar" not in panel.sections
    panel.editors[("colorbar",)].widget.click()
    assert _artists(window)[0].colorbar is not None
    assert ("colorbar", "label") in panel.editors


def test_the_array_and_colour_map_are_chosen_from_lists(panel, window) -> None:
    document = window.document
    image = _artists(window)[0]
    document.select(image.id)
    data = panel.editors[("data",)].widget
    assert data.currentText() == "map.npz[counts]"
    cmap = panel.editors[("cmap",)].widget
    cmap.activated.emit(cmap.findText("magma"))
    assert _artists(window)[0].cmap == "magma"
    document.push(SetField(image.id, ("cmap",), "jet"))  # any name stays usable
    assert panel.editors[("cmap",)].widget.currentText() == "jet"


def test_clicking_the_color_bar_selects_the_image(qtbot, window, grid) -> None:
    window.import_numpy(grid)
    image = _artists(window)[0]
    preview = Preview(window.document)
    qtbot.addWidget(preview)
    preview.resize(900, 700)
    preview.show()
    qtbot.waitExposed(preview)
    preview.grab()
    colorbar = next(ax for ax in preview._figure.axes if ax.get_gid() == image.id)
    box = colorbar.bbox
    centre = preview._to_widget((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
    assert preview.object_at(centre) == image.id
    assert preview.axes_at(centre) is None  # never zoomed like a panel
    panel = preview._figure.axes[0]
    inside = preview._to_widget(
        (panel.bbox.x0 + panel.bbox.x1) / 2, (panel.bbox.y0 + panel.bbox.y1) / 2
    )
    assert preview.object_at(inside) == image.id


def test_columns_of_a_2d_array_can_be_plotted(window, grid) -> None:
    window.import_numpy(grid)
    source = window.document.project.sources[0]
    columns = dict(window.document.column_choices())
    assert "map.npz[counts]: 0" in columns
    assert columns["map.npz[counts]: 0"].source == source.id
