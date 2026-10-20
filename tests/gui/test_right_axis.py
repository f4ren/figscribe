"""The right y axis in the GUI."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.commands import InsertItem, SetField
from figscribe.fit import add_fit
from figscribe.gui import Document
from figscribe.gui.outline import COLOR_ROLE, Outline
from figscribe.gui.properties import PropertyPanel
from figscribe.model import AxisSpec, FitCurve, LinePlot, PredefinedFit


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


@pytest.fixture
def panel(qtbot, document: Document) -> PropertyPanel:
    widget = PropertyPanel(document)
    qtbot.addWidget(widget)
    return widget


def _axes(document: Document):
    return document.figure.axes[0]


def test_a_panel_gets_and_loses_its_right_axis(panel, document) -> None:
    axes = _axes(document)
    document.select(axes.id)
    switch = panel.editors[("y_right",)].widget
    assert not switch.isChecked() and "Right y axis" not in panel.sections
    switch.setChecked(True)
    assert _axes(document).y_right is not None
    assert document.history.undo_text == "Add the right y axis"
    assert "Right y axis" in panel.sections
    assert ("y_right", "label") in panel.editors

    plot = _axes(document).artists[0]
    document.push(_right(plot))
    document.select(axes.id)
    panel.editors[("y_right",)].widget.setChecked(False)
    assert _axes(document).y_right is None
    assert _axes(document).artists[0].axis == "left"  # its plots came back
    document.undo()
    assert _axes(document).artists[0].axis == "right"


def test_choosing_the_right_axis_creates_it(panel, document) -> None:
    plot = _axes(document).artists[0]
    document.select(plot.id)
    combo = panel.editors[("axis",)].widget
    combo.activated.emit(combo.findText("right"))
    assert _axes(document).y_right is not None
    assert _axes(document).artists[0].axis == "right"
    assert document.history.undo_text == "Draw against a new right y axis"
    document.undo()
    assert _axes(document).y_right is None


def test_each_axis_has_its_own_colours(qtbot, document: Document) -> None:
    axes = _axes(document)
    data = axes.artists[0]
    document.push(_right(data))  # creates nothing: only sets the axis
    document.push(SetField(axes.id, ("y_right",), AxisSpec()))
    left = LinePlot(x=data.x, y=data.y)
    document.push(InsertItem(axes.id, "artists", left))
    outline = Outline(document)
    qtbot.addWidget(outline)
    # Both are the first plot on their side: both blue.
    first = outline.item_for(data.id).data(0, COLOR_ROLE)
    second = outline.item_for(left.id).data(0, COLOR_ROLE)
    assert first == second == "#1f77b4"


def test_a_fit_is_drawn_against_its_datas_axis(document: Document) -> None:
    plot = _axes(document).artists[0]
    document.push(_right(plot))
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    document.push(add_fit(document.project, fit))
    assert _axes(document).artists[-1].axis == "right"


def _right(plot):
    return SetField(plot.id, ("axis",), "right")
