"""Panels in the GUI: adding beside or inside, deleting, editing the position."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF

from figscribe.commands import remove_axes
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
        "Add note…",
        "Add line or range",
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
    assert _menu_texts(insets_menu) == [
        "Add note…",
        "Add line or range",
        "Delete panel",
    ]


def test_deleting_from_the_context_menu(window: MainWindow) -> None:
    plot = window.document.figure.axes[0].artists[0]
    menu = window.outline.context_menu(plot.id)
    assert _menu_texts(menu) == ["Hide", "Bring to front", "Send to back", "Delete"]
    menu.actions()[0].trigger()
    assert window.document.figure.axes[0].artists[0].visible is False
    window.outline.context_menu(plot.id).actions()[-1].trigger()
    assert window.document.figure.axes[0].artists == []

    axes = window.document.figure.axes[0]
    window.outline.context_menu(axes.id).actions()[-1].trigger()
    assert window.document.figure.axes == []
    figure_menu = window.outline.context_menu(window.document.figure.id)
    assert _menu_texts(figure_menu) == [
        "Add a panel",
        "Rename…",
        "Duplicate",
        "Move up",
        "Move down",
        "Delete figure",
    ]
    figure_menu.actions()[0].trigger()
    assert len(window.document.figure.axes) == 1


def test_removing_a_data_file_asks_what_goes_with_it(window: MainWindow) -> None:
    document = window.document
    source = document.project.sources[0]
    asked = []
    window.ask = lambda title, question: asked.append(question) or False
    menu = window.outline.context_menu(source.id)
    assert _menu_texts(menu) == ["Remove data file"]
    menu.actions()[0].trigger()
    assert "scan.csv" in asked[0] and "measurement" in asked[0]
    assert document.project.sources == [source]  # "No" keeps everything

    window.ask = lambda title, question: True
    document.select(source.id)
    assert window.delete_action.isEnabled()
    window.delete_action.trigger()
    assert document.project.sources == []
    assert document.figure.axes[0].artists == []
    assert document.selected is None
    document.undo()
    assert document.project.sources[0].id == source.id


def test_an_unused_data_file_is_removed_without_asking(window: MainWindow) -> None:
    document = window.document
    for axes in list(document.figure.axes):
        document.push(remove_axes(document.project, axes.id))
    asked = []
    window.ask = lambda title, question: asked.append(question) or True
    window.outline.context_menu(document.project.sources[0].id).actions()[0].trigger()
    assert document.project.sources == [] and asked == []


def test_plots_are_brought_to_front_and_sent_back(window: MainWindow) -> None:
    from figscribe.commands import InsertItem
    from figscribe.model import LinePlot

    axes = window.document.figure.axes[0]
    data = axes.artists[0]
    line = LinePlot(x=data.x, y=data.y)
    window.document.push(InsertItem(axes.id, "artists", line))

    def action(oid: str, text: str):
        menu = window.outline.context_menu(oid)
        return next(a for a in menu.actions() if a.text() == text)

    assert not action(data.id, "Send to back").isEnabled()  # equal order: drawn first
    action(data.id, "Bring to front").trigger()
    artists = window.document.figure.axes[0].artists
    assert artists[0].zorder > artists[1].zorder
    assert window.document.history.undo_text == "Bring to front"
    assert not action(data.id, "Bring to front").isEnabled()
    action(data.id, "Send to back").trigger()
    artists = window.document.figure.axes[0].artists
    assert artists[0].zorder < artists[1].zorder


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
