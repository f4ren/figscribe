"""Several plots chosen together in the outline, changed and deleted at once."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.model import LinePlot, ScatterPlot


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
    data = document.figure.axes[0].artists[0]
    axes = document.figure.axes[0]
    from figscribe.commands import InsertItem, Macro

    document.push(
        Macro(
            "Add two plots",
            [
                InsertItem(axes.id, "artists", LinePlot(x=data.x, y=data.y)),
                InsertItem(
                    axes.id, "artists", ScatterPlot(x=data.x, y=data.y, color="C2")
                ),
            ],
        )
    )
    return win


def _click(window: MainWindow, oid: str, modifier=Qt.KeyboardModifier.NoModifier):
    tree = window.outline
    item = tree.item_for(oid)
    rect = tree.visualItemRect(item)
    QTest.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, modifier, rect.center()
    )


def _plots(window: MainWindow):
    return window.document.figure.axes[0].artists


def test_ctrl_click_chooses_several_plots(window: MainWindow) -> None:
    bars, line, points = _plots(window)
    _click(window, bars.id)
    _click(window, points.id, Qt.KeyboardModifier.ControlModifier)
    assert window.document.selection == [bars.id, points.id]
    assert window.document.selected == points.id  # the one clicked last
    panel = window.properties
    assert panel._kicker.text() == "2 PLOTS"
    # Only what both have: a scatter plot has no line, error bars no size.
    assert set(panel.editors) >= {("color",), ("marker",), ("alpha",)}
    assert ("linewidth",) not in panel.editors and ("size",) not in panel.editors
    _click(window, line.id, Qt.KeyboardModifier.ShiftModifier)
    assert set(window.document.selection) == {bars.id, line.id, points.id}
    _click(window, line.id)  # a plain click chooses one again
    assert window.document.selection == [line.id]
    assert window.properties._kicker.text() != "3 PLOTS"


def test_a_setting_changes_on_every_plot_chosen(window: MainWindow) -> None:
    bars, line, points = _plots(window)
    _click(window, bars.id)
    _click(window, line.id, Qt.KeyboardModifier.ControlModifier)
    panel = window.properties
    marker = panel.editors[("marker",)].widget
    assert marker.currentText() == "several"  # a circle and none
    color = panel.editors[("color",)].line
    assert color.text() == "" and color.placeholderText() == "automatic"
    color.setText("tab:red")
    color.editingFinished.emit()
    assert [p.color for p in _plots(window)[:2]] == ["tab:red", "tab:red"]
    assert _plots(window)[2].color == "C2"  # not chosen, not changed
    assert window.document.history.undo_text == "Change 2 plots"
    assert window.properties.editors[("color",)].line.text() == "tab:red"
    marker = panel.editors[("marker",)].widget
    marker.activated.emit(marker.findText("Square"))
    assert [p.marker for p in _plots(window)[:2]] == ["s", "s"]
    window.document.undo()
    window.document.undo()
    assert [p.color for p in _plots(window)[:2]] == [None, None]


def test_visible_from_several_values(window: MainWindow) -> None:
    bars, line, _ = _plots(window)
    window.outline.set_visible(line.id, False)
    _click(window, bars.id)
    _click(window, line.id, Qt.KeyboardModifier.ControlModifier)
    box: QCheckBox = window.properties.editors[("visible",)].widget
    assert box.checkState() == Qt.CheckState.PartiallyChecked
    box.click()
    assert all(p.visible for p in _plots(window)[:2])


def test_delete_removes_every_plot_chosen(window: MainWindow) -> None:
    bars, line, points = _plots(window)
    _click(window, line.id)
    _click(window, points.id, Qt.KeyboardModifier.ControlModifier)
    window.delete_action.trigger()
    assert [p.id for p in _plots(window)] == [bars.id]
    assert window.document.history.undo_text == "Remove 2 plots"
    assert window.document.selection == []
    window.document.undo()
    assert len(_plots(window)) == 3


def test_a_panel_among_them_chooses_only_the_row_clicked(window: MainWindow) -> None:
    bars = _plots(window)[0]
    panel = window.document.figure.axes[0]
    _click(window, bars.id)
    _click(window, panel.id, Qt.KeyboardModifier.ControlModifier)
    assert window.document.selection == [panel.id]
