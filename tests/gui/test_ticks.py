"""Tick style and value prefixes in the property panel."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import Document
from figscribe.gui.properties import PropertyPanel


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


@pytest.fixture
def panel(qtbot, document: Document) -> PropertyPanel:
    widget = PropertyPanel(document)
    qtbot.addWidget(widget)
    return widget


def _choose(panel: PropertyPanel, path: tuple, text: str) -> None:
    combo = panel.editors[path].widget
    index = combo.findText(text)
    assert index >= 0, [combo.itemText(i) for i in range(combo.count())]
    combo.activated.emit(index)


def test_the_figure_sets_the_tick_style(panel, document) -> None:
    document.select(document.figure.id)
    combo = panel.editors[("tick_direction",)].widget
    assert combo.currentText() == "style default"
    _choose(panel, ("tick_direction",), "inward")
    panel.editors[("ticks_all_sides",)].widget.click()
    figure = document.figure
    assert figure.tick_direction == "in" and figure.ticks_all_sides
    assert "Style" in panel.sections


def test_the_figure_sets_frame_and_tick_widths(panel, document) -> None:
    document.select(document.figure.id)
    for name, text in [("frame_width", "1.2"), ("tick_length", "5")]:
        line = panel.editors[(name,)].line
        assert line.placeholderText() == "default"
        line.setText(text)
        line.editingFinished.emit()
    figure = document.figure
    assert (figure.frame_width, figure.tick_length) == (1.2, 5.0)
    assert figure.tick_width is None  # untouched: the style's


def test_a_panel_sets_its_grid_line_width_and_style(panel, document) -> None:
    document.select(document.figure.axes[0].id)
    line = panel.editors[("grid_linewidth",)].line
    line.setText("0.4")
    line.editingFinished.emit()
    _choose(panel, ("grid_linestyle",), "Dotted")
    combo = panel.editors[("grid_linestyle",)].widget
    assert combo.findText("None") < 0  # a grid without a line is no grid
    axes = document.figure.axes[0]
    assert (axes.grid_linewidth, axes.grid_linestyle) == (0.4, ":")


def test_an_axis_shows_its_values_with_a_prefix(panel, document) -> None:
    axes = document.figure.axes[0]
    document.select(f"{axes.id}/x")
    combo = panel.axis_form.prefix
    assert combo.currentText() == "s, as in the data"
    combo.activated.emit(combo.findText("ms"))
    assert document.figure.axes[0].x.prefix == "m"
    document.undo()
    assert document.figure.axes[0].x.prefix is None
