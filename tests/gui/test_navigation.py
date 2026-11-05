"""Where am I (roadmap U9): a path above the settings, whose parts lead back,
and the axes as rows of the outline."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from figscribe.commands import InsertItem, SetField, add_panel
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.document import axis_id
from figscribe.gui.outline import ID_ROLE
from figscribe.gui.path import path_to
from figscribe.model import Axes, AxisSpec, Figure, Inset


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _panel(window: MainWindow) -> Axes:
    return window.document.figure.axes[0]


def _rows(window: MainWindow) -> list[tuple[str | None, str]]:
    outline = window.outline
    items = [outline.topLevelItem(i) for i in range(outline.topLevelItemCount())]
    return [(item.data(0, ID_ROLE), item.text(0)) for item in items]


def _click_row(window: MainWindow, oid: str, column: int = 0) -> None:
    outline = window.outline
    item = outline.item_for(oid)
    rect = outline.visualItemRect(item)
    x = rect.left() + 5
    if column:
        x = outline.header().sectionPosition(column) + 5
    QTest.mouseClick(
        outline.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(x, rect.center().y()),
    )


def _crumbs(window: MainWindow) -> list[str]:
    """What the path above the settings says, left to right."""
    return window.properties.path_texts()


# --- the path, as data --------------------------------------------------------


def test_the_path_of_a_plot_is_figure_panel_kind(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    plot = panel.artists[0]
    assert path_to(document, plot.id) == [
        (document.figure.name, document.figure.id),
        ("Panel A", panel.id),
        ("Error bar plot", None),
    ]


def test_the_path_of_an_axis_goes_through_its_panel(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    assert path_to(document, axis_id(panel.id, "x")) == [
        (document.figure.name, document.figure.id),
        ("Panel A", panel.id),
        ("X axis", None),
    ]


def test_the_path_of_a_panel_and_a_figure_and_a_data_file(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    assert path_to(document, panel.id) == [
        (document.figure.name, document.figure.id),
        ("Panel A", None),
    ]
    assert path_to(document, document.figure.id) == [("Figure", None)]
    source = document.project.sources[0]
    assert path_to(document, source.id) == [("Data file", None)]


def test_an_inset_is_reached_through_its_panel(window: MainWindow) -> None:
    document = window.document
    host = _panel(window)
    inset = Axes(inset=Inset(parent=host.id))
    document.push(InsertItem(document.figure.id, "axes", inset))
    inset = document.figure.axes[-1]
    assert [text for text, _ in path_to(document, inset.id)] == [
        document.figure.name,
        "Panel A",
        "Inset",
    ]
    assert path_to(document, inset.id)[1][1] == host.id
    assert [text for text, _ in path_to(document, axis_id(inset.id, "y"))] == [
        document.figure.name,
        "Panel A",
        "Inset",
        "Y axis",
    ]


# --- the path in the panel ----------------------------------------------------


def test_the_panel_shows_the_path_of_the_selection(window: MainWindow) -> None:
    window.document.select(axis_id(_panel(window).id, "y"))
    assert _crumbs(window) == [window.document.figure.name, "Panel A", "Y axis"]


def test_a_part_of_the_path_leads_back(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    document.select(axis_id(panel.id, "x"))
    buttons = window.properties.path_buttons()
    assert [b.text() for b in buttons] == [document.figure.name, "Panel A"]
    buttons[1].click()  # back to the panel
    assert document.selected == panel.id
    assert window.properties.axis_form is None
    window.properties.path_buttons()[0].click()  # and to the figure
    assert document.selected == document.figure.id
    assert window.properties.path_buttons() == []  # the figure has nothing above


def test_the_path_follows_a_rename(window: MainWindow) -> None:
    document = window.document
    document.select(axis_id(_panel(window).id, "x"))
    document.push(SetField(document.figure.id, ("name",), "Renamed"))
    assert _crumbs(window)[0] == "Renamed"


def test_several_plots_keep_their_header(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    from figscribe.model import LinePlot

    document.push(
        InsertItem(
            panel.id,
            "artists",
            LinePlot(x=panel.artists[0].x, y=panel.artists[0].y),
        )
    )
    document.select_many([a.id for a in _panel(window).artists])
    assert window.properties.path_buttons() == []
    assert "PLOTS" in window.properties._kicker.text()


# --- the axes in the outline --------------------------------------------------


def test_every_panel_lists_its_axes_before_its_plots(window: MainWindow) -> None:
    panel = _panel(window)
    ids = [oid for oid, _ in _rows(window)]
    heading = ids.index(panel.id)
    assert ids[heading + 1 : heading + 3] == [
        axis_id(panel.id, "x"),
        axis_id(panel.id, "y"),
    ]
    assert ids[heading + 3] == panel.artists[0].id
    texts = dict(_rows(window))
    assert texts[axis_id(panel.id, "x")].startswith("X axis")
    assert "t (s)" in texts[axis_id(panel.id, "x")]


def test_the_right_y_axis_has_a_row_only_when_there_is_one(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    assert window.outline.item_for(axis_id(panel.id, "y_right")) is None
    document.push(SetField(panel.id, ("y_right",), AxisSpec(label="dU")))
    item = window.outline.item_for(axis_id(panel.id, "y_right"))
    assert item is not None and item.text(0).startswith("Right y axis")
    document.undo()
    assert window.outline.item_for(axis_id(panel.id, "y_right")) is None


def test_clicking_an_axis_row_shows_its_form(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    _click_row(window, axis_id(panel.id, "y"))
    assert document.selected == axis_id(panel.id, "y")
    assert window.properties.axis_form is not None
    assert window.outline.currentItem().data(0, ID_ROLE) == axis_id(panel.id, "y")
    assert _crumbs(window)[-1] == "Y axis"


def test_choosing_an_axis_in_the_figure_selects_its_row(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    document.select(axis_id(panel.id, "x"))  # what a click on the axis does
    assert window.outline.currentItem().data(0, ID_ROLE) == axis_id(panel.id, "x")


def test_a_click_beside_an_axis_row_does_nothing_else(window: MainWindow) -> None:
    panel = _panel(window)
    before = window.document.history.undo_text
    _click_row(window, axis_id(panel.id, "x"), column=1)  # where a plot's eye is
    assert window.document.history.undo_text == before


def test_an_axis_of_another_figure_brings_that_figure_up(window: MainWindow) -> None:
    document = window.document
    document.push(InsertItem(None, "figures", Figure(name="Second", axes=[Axes()])))
    first, second = document.project.figures
    document.select(first.id)
    assert document.figure is first
    _click_row(window, axis_id(second.axes[0].id, "x"))
    assert document.figure is second
    assert document.selected == axis_id(second.axes[0].id, "x")
    assert window.properties.axis_form is not None


def test_an_axis_row_offers_the_range_for_all_panels(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    menu = window.outline.context_menu(axis_id(panel.id, "x"))
    (entry,) = menu.actions()
    assert entry.text() == "Same x range in all panels" and not entry.isEnabled()
    document.push(add_panel(document.project, panel.id, "below")[0])
    menu = window.outline.context_menu(axis_id(panel.id, "x"))
    assert menu.actions()[0].isEnabled()
    asked = []
    window.outline.same_range_requested.connect(lambda *a: asked.append(a))
    menu.actions()[0].trigger()
    assert asked == [(panel.id, "x")]


def test_the_right_y_axis_and_insets_offer_no_menu(window: MainWindow) -> None:
    document = window.document
    panel = _panel(window)
    document.push(SetField(panel.id, ("y_right",), AxisSpec(label="dU")))
    assert window.outline.context_menu(axis_id(panel.id, "y_right")) is None
    document.push(
        InsertItem(document.figure.id, "axes", Axes(inset=Inset(parent=panel.id)))
    )
    inset = document.figure.axes[-1]
    assert window.outline.context_menu(axis_id(inset.id, "x")) is None


def test_the_path_buttons_are_real_buttons(window: MainWindow) -> None:
    window.document.select(axis_id(_panel(window).id, "x"))
    assert all(isinstance(b, QPushButton) for b in window.properties.path_buttons())


def test_the_range_of_an_axis_row_reaches_the_other_panels(
    window: MainWindow,
) -> None:
    document = window.document
    panel = _panel(window)
    document.push(SetField(panel.id, ("x", "limits"), (1.0, 4.0)))
    command, below = add_panel(document.project, panel.id, "below")
    document.push(command)
    menu = window.outline.context_menu(axis_id(panel.id, "x"))
    menu.actions()[0].trigger()
    assert document.figure.axes[1].x.limits == (1.0, 4.0)
