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
    panel.editors[("ticks_all_sides",)].widget.setChecked(True)
    figure = document.figure
    assert figure.tick_direction == "in" and figure.ticks_all_sides
    assert "Style" in panel.sections


def test_an_axis_shows_its_values_with_a_prefix(panel, document) -> None:
    axes = document.figure.axes[0]
    document.select(f"{axes.id}/x")
    combo = panel.axis_form.prefix
    assert combo.currentText() == "s, as in the data"
    combo.activated.emit(combo.findText("ms"))
    assert document.figure.axes[0].x.prefix == "m"
    document.undo()
    assert document.figure.axes[0].x.prefix is None
