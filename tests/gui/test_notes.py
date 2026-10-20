"""Notes and histograms in the GUI."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.plotdialog import PlotDialog
from figscribe.model import Annotation, Histogram


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _add_note(window: MainWindow, text: str = "peak") -> Annotation:
    window.ask_text = lambda title, prompt: text
    window.note_action.trigger()
    return window.document.figure.axes[0].artists[-1]


def test_a_note_lands_in_the_middle_of_the_panel(window: MainWindow) -> None:
    note = _add_note(window)
    assert isinstance(note, Annotation)
    assert (note.text, note.position, note.coords) == ("peak", (0.5, 0.5), "axes")
    assert window.document.selected == note.id
    assert window.preview.error is None
    assert window.outline.item_for(note.id).text(0) == "Note: peak"

    window.ask_text = lambda title, prompt: None  # cancelled
    window.note_action.trigger()
    assert window.document.figure.axes[0].artists[-1].id == note.id


def test_dragging_a_note_moves_it(qtbot, window: MainWindow) -> None:
    note = _add_note(window, "drag me")
    preview = window.preview
    preview.grab()
    (text,) = [t for t in preview._figure.axes[0].texts if t.get_gid() == note.id]
    box = text.get_window_extent()
    start = preview._to_widget((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
    start = start.toPoint()
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(preview, start + QPoint(-80, 50))
    assert preview._moved_legend_rect() is not None
    qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=start + QPoint(-80, 50))
    moved = window.document.figure.axes[0].artists[-1]
    assert moved.position[0] < 0.5 and moved.position[1] < 0.5
    assert window.document.history.undo_text == "Set position"
    preview.grab()
    (text,) = [t for t in preview._figure.axes[0].texts if t.get_gid() == note.id]
    after = text.get_window_extent()
    assert after.x0 == pytest.approx(box.x0 - 80, abs=1.5)
    assert after.y0 == pytest.approx(box.y0 - 50, abs=1.5)


def test_a_histogram_from_the_plot_dialog(window: MainWindow) -> None:
    def histogram(dialog) -> bool:
        assert isinstance(dialog, PlotDialog)
        dialog.kind.setCurrentText("Histogram")
        assert not dialog.x.isEnabled()
        return True

    window.run_dialog = histogram
    window.add_plot()
    artist = window.document.figure.axes[0].artists[-1]
    assert isinstance(artist, Histogram) and artist.values.column == "U"
    assert window.preview.error is None

    panel = window.properties
    window.document.select(artist.id)
    line = panel.editors[("bins",)].line
    assert line.text() == "20"
    line.setText("0, 0.5, 1")
    line.editingFinished.emit()
    assert window.document.figure.axes[0].artists[-1].bins == [0.0, 0.5, 1.0]
    line.setText("8")
    line.editingFinished.emit()
    assert window.document.figure.axes[0].artists[-1].bins == 8
