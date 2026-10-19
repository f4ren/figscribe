"""Panels in the GUI: adding beside or inside, deleting, editing the position."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.names import panel_name
from figscribe.gui.properties import PropertyPanel


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    return win


def _menu_texts(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_insert_menu_adds_a_panel_to_the_right(window: MainWindow) -> None:
    first = window.document.figure.axes[0]
    window.document.select(first.artists[0].id)  # the panel of the selected plot
    window.panel_actions["right"].trigger()
    figure = window.document.figure
    assert figure.layout.cols == 2 and len(figure.axes) == 2
    new = figure.axes[1]
    assert window.document.selected == new.id
    assert window.outline.item_for(new.id).text(0) == "PANEL B · RIGHT"
    assert window.preview.error is None
    window.document.undo()
    assert len(window.document.figure.axes) == 1


def test_an_inset_from_the_context_menu(window: MainWindow) -> None:
    host = window.document.figure.axes[0]
    menu = window.outline.context_menu(host.id)
    assert _menu_texts(menu) == [
        "Add panel to the right",
        "Add panel to the left",
        "Add panel above",
        "Add panel below",
        "Add inset",
        "Delete panel",
    ]
    next(a for a in menu.actions() if a.text() == "Add inset").trigger()
    inset = window.document.figure.axes[1]
    assert inset.inset.parent == host.id
    assert panel_name(window.document.figure, inset) == "Panel B · inset in A"
    assert window.preview.error is None

    # A click inside the inset selects the inset, not the panel around it.
    preview = window.preview
    preview.resize(800, 600)
    preview.grab()  # paint once, which places the image
    child = preview._figure.axes[0].child_axes[0]
    box = child.get_window_extent()
    middle = preview._to_widget((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
    assert preview.object_at(QPointF(middle)) == inset.id

    insets_menu = window.outline.context_menu(inset.id)
    assert _menu_texts(insets_menu) == ["Delete panel"]


def test_deleting_from_the_context_menu(window: MainWindow) -> None:
    plot = window.document.figure.axes[0].artists[0]
    menu = window.outline.context_menu(plot.id)
    assert _menu_texts(menu) == ["Hide", "Delete"]
    menu.actions()[0].trigger()
    assert window.document.figure.axes[0].artists[0].visible is False
    window.outline.context_menu(plot.id).actions()[-1].trigger()
    assert window.document.figure.axes[0].artists == []

    axes = window.document.figure.axes[0]
    window.outline.context_menu(axes.id).actions()[-1].trigger()
    assert window.document.figure.axes == []
    figure_menu = window.outline.context_menu(window.document.figure.id)
    assert _menu_texts(figure_menu) == ["Add a panel"]
    figure_menu.actions()[0].trigger()
    assert len(window.document.figure.axes) == 1


def test_the_position_is_a_section_of_its_own(qtbot, window: MainWindow) -> None:
    panel: PropertyPanel = window.properties
    host = window.document.figure.axes[0]
    window.document.select(host.id)
    assert "Position" in panel.sections and ("row",) in panel.editors
    window.add_panel("inset", host.id)
    inset = window.document.figure.axes[1]
    assert window.document.selected == inset.id
    assert "Position" not in panel.sections and "Inset" in panel.sections
    line = panel.editors[("inset", "bounds")].line
    line.setText("0.1, 0.1, 0.3, 0.3")
    line.editingFinished.emit()
    assert window.document.figure.axes[1].inset.bounds == (0.1, 0.1, 0.3, 0.3)
    line.setText("0.1, 0.1")
    line.editingFinished.emit()
    assert "four numbers" in panel.error
