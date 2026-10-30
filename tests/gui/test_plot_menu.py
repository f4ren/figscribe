"""A right-click on a plot in the preview: style it like another, change its
drawing order, fit it or hide it."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF

from figscribe.commands import InsertItem, copy_style
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.model import LinePlot


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    document = win.document
    bars = document.figure.axes[0].artists[0]
    line = LinePlot(
        x=bars.x, y=bars.yerr, color="tab:red", linestyle="--", label="noise"
    )
    document.push(InsertItem(document.figure.axes[0].id, "artists", line))
    win.preview.grab()
    return win


def _point(window: MainWindow, row: int) -> QPointF:
    """Where row `row` of the error bars is drawn, in the preview."""
    preview, document = window.preview, window.document
    plot = document.figure.axes[0].artists[0]
    x, y = document.data(plot.x)[row], document.data(plot.y)[row]
    ax = next(
        a for a in preview._figure.axes if a.get_gid() == document.figure.axes[0].id
    )
    return preview._to_widget(*ax.transData.transform((x, y)))


def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _entry(menu, text: str):
    return next(a for a in menu.actions() if a.text() == text)


def test_the_menu_of_a_plot(window: MainWindow) -> None:
    menu = window.preview.context_menu(_point(window, 20))
    texts = _texts(menu)
    assert texts[:5] == ["Style like", "Bring to front", "Send to back", "Fit…", "Hide"]
    assert "Leave out row 21" in texts  # what the point under it offers stays
    assert not _entry(menu, "Send to back").isEnabled()  # drawn first already


def test_style_like_another_plot(window: MainWindow) -> None:
    menu = window.preview.context_menu(_point(window, 20))
    like_action = _entry(menu, "Style like")  # kept: PySide6 before 6.12 makes
    like = like_action.menu()  # the menu invalid once this action is gone
    assert _texts(like) == ["noise"]
    like.actions()[0].trigger()
    bars = window.document.figure.axes[0].artists[0]
    assert (bars.color, bars.linestyle) == ("tab:red", "--")
    assert bars.marker == "o"  # a line's "no marker" is none for error bars
    assert window.document.history.undo_text == "Style like noise"
    window.document.undo()
    assert window.document.figure.axes[0].artists[0].color is None


def test_bring_to_front_and_hide(window: MainWindow) -> None:
    preview, document = window.preview, window.document
    _entry(preview.context_menu(_point(window, 20)), "Bring to front").trigger()
    bars, line = document.figure.axes[0].artists
    assert bars.zorder > line.zorder
    preview.grab()
    _entry(preview.context_menu(_point(window, 20)), "Hide").trigger()
    assert document.figure.axes[0].artists[0].visible is False
    assert document.history.undo_text == "Hide"


def test_fit_from_the_menu_opens_the_fit_dialog(window: MainWindow) -> None:
    shown = []
    window.run_dialog = lambda dialog: shown.append(dialog) or False
    window.document.select(None)
    _entry(window.preview.context_menu(_point(window, 20)), "Fit…").trigger()
    bars = window.document.figure.axes[0].artists[0]
    assert window.document.selected == bars.id
    assert len(shown) == 1  # the fit dialog, for the plot clicked


def test_copy_style_takes_what_the_target_can_have(window: MainWindow) -> None:
    project = window.document.project
    bars, line = project.figures[0].axes[0].artists
    command = copy_style(project, line.id, bars.id)
    names = [step.path[0] for step in command.steps]
    assert "capsize" not in names  # a line has no caps
    assert "marker" in names and "linestyle" in names
