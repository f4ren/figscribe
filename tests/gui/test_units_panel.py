"""A plot's units and range in the property panel (roadmap F11.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QLineEdit

from figscribe.commands import InsertItem
from figscribe.gui import Document
from figscribe.gui.properties import PropertyPanel
from figscribe.model import AllanDeviationPlot, Conversion


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


@pytest.fixture
def panel(qtbot, document: Document) -> PropertyPanel:
    widget = PropertyPanel(document)
    qtbot.addWidget(widget)
    return widget


def _plot(document: Document):
    return document.figure.axes[0].artists[0]


def _choose(panel: PropertyPanel, path: tuple, text: str) -> None:
    combo = panel.editors[path].widget
    index = combo.findText(text)
    assert index >= 0, [combo.itemText(i) for i in range(combo.count())]
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def _type(panel: PropertyPanel, path: tuple, text: str) -> None:
    line = panel.editors[path].widget
    line.setText(text)
    line.editingFinished.emit()


def _ends(panel: PropertyPanel, low: str, high: str) -> None:
    first, second = panel.editors[("x_range",)].widget.findChildren(QLineEdit)
    first.setText(low)
    second.setText(high)
    second.editingFinished.emit()


def test_x_is_shown_in_another_unit_from_a_list(panel, document) -> None:
    document.select(_plot(document).id)
    combo = panel.editors[("x_conversion",)].widget
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert texts == [
        "as in the file",
        "min (÷ 60)",
        "h (÷ 3600)",
        "days (÷ 86 400)",
        "ms (× 1000)",
        "another factor",
    ]
    assert ("x_conversion", "from_start") not in panel.editors
    _choose(panel, ("x_conversion",), "ms (× 1000)")
    assert _plot(document).x_conversion == Conversion(factor=1000.0, unit="ms")
    assert document.figure.axes[0].x.unit == "ms"  # the axis follows
    assert document.history.undo_text == "Show x in ms"

    panel.editors[("x_conversion", "from_start")].widget.click()
    assert _plot(document).x_conversion.from_start
    assert ("x_conversion", "factor") not in panel.editors  # a unit of the list


def test_another_factor_is_typed_with_its_unit(panel, document) -> None:
    document.select(_plot(document).id)
    _choose(panel, ("y_conversion",), "another factor")
    _type(panel, ("y_conversion", "factor"), "1000")
    _type(panel, ("y_conversion", "unit"), "mV")
    assert _plot(document).y_conversion == Conversion(factor=1000.0, unit="mV")
    assert document.figure.axes[0].y.unit == "mV"
    _type(panel, ("y_conversion", "factor"), "0")
    assert "Factor" in panel.error and _plot(document).y_conversion.factor == 1000


def test_a_range_takes_both_ends_and_says_why_it_is_refused(panel, document) -> None:
    document.select(_plot(document).id)
    _ends(panel, "2", "")
    assert "both ends" in panel.error and _plot(document).x_range is None
    _ends(panel, "2", "8")
    assert _plot(document).x_range == (2.0, 8.0)
    assert document.history.undo_text == "Use only x from 2 to 8"
    _ends(panel, "", "")
    assert _plot(document).x_range is None


def test_an_allan_deviation_counts_its_range_in_time(panel, document) -> None:
    data = _plot(document)
    allan = AllanDeviationPlot(values=data.y, time=data.x)
    document.push(InsertItem(document.figure.axes[0].id, "artists", allan))
    document.select(allan.id)
    _choose(panel, ("x_conversion",), "min (÷ 60)")
    # tau starts at tau0 whatever, so there is nothing to start at 0.
    assert ("x_conversion", "from_start") not in panel.editors
    captions = [label.text() for label in panel.widget().findChildren(QLabel)]
    assert "Use only times" in captions
