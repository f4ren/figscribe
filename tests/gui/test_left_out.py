"""Leaving points out by right-clicking them in the preview."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF

from figscribe.gui import Document
from figscribe.gui.preview import Preview


@pytest.fixture
def preview(qtbot, example: Path) -> Preview:
    widget = Preview(Document.open(example))
    qtbot.addWidget(widget)
    widget.resize(900, 700)
    widget.show()
    qtbot.waitExposed(widget)
    widget.grab()  # paint once, which places the image
    return widget


def _point(preview: Preview, row: int) -> QPointF:
    """Where row `row` of the example's data is drawn, in widget coordinates."""
    document = preview.document
    plot = document.figure.axes[0].artists[0]
    x, y = document.data(plot.x)[row], document.data(plot.y)[row]
    ax = next(
        a for a in preview._figure.axes if a.get_gid() == document.figure.axes[0].id
    )
    return preview._to_widget(*ax.transData.transform((x, y)))


def _entry(menu, starts: str):
    return next(a for a in menu.actions() if a.text().startswith(starts))


def test_a_point_is_left_out_and_taken_back_in(preview: Preview) -> None:
    document = preview.document
    plot = document.figure.axes[0].artists[0]
    menu = preview.context_menu(_point(preview, 12))
    _entry(menu, "Leave out row 13").trigger()
    assert document.figure.axes[0].artists[0].left_out == [12]
    preview.grab()  # drawn again, the point now in grey
    menu = preview.context_menu(_point(preview, 12))
    _entry(menu, "Take row 13 back in").trigger()
    assert document.figure.axes[0].artists[0].left_out == []
    assert document.history.undo_text == "Take row 13 back in"
    assert plot.id == document.figure.axes[0].artists[0].id


def test_no_menu_away_from_the_points(preview: Preview) -> None:
    assert preview.context_menu(QPointF(3, 3)) is None


def test_markers_are_chosen_from_a_list_with_every_kind(
    qtbot, preview: Preview
) -> None:
    from figscribe.commands import SetField
    from figscribe.gui.properties import PropertyPanel

    document = preview.document
    plot = document.figure.axes[0].artists[0]
    document.push(SetField(plot.id, ("left_out",), [12]))
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    document.select(plot.id)
    combo = panel.editors[("marker",)].widget
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert {"Circle", "Star", "Triangle down", "Plus", "No marker"} <= set(texts)
    assert not combo.itemIcon(texts.index("Star")).isNull()
    out = panel.editors[("left_out_marker",)]
    texts = [out.widget.itemText(i) for i in range(out.widget.count())]
    assert texts[:2] == ["No marker", "Like the plot"]
    out.widget.activated.emit(texts.index("Star"))
    assert document.figure.axes[0].artists[0].left_out_marker == "*"
    out = panel.editors[("left_out_marker",)]
    out.widget.activated.emit(0)
    assert document.figure.axes[0].artists[0].left_out_marker is None
    style = panel.editors[("left_out_linestyle",)].widget
    assert style.itemText(0) == "Like the plot"


def test_a_custom_marker_can_be_typed(qtbot, preview: Preview) -> None:
    from figscribe.gui.properties import PropertyPanel

    document = preview.document
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    document.select(document.figure.axes[0].artists[0].id)

    def choose(text: str) -> None:
        combo = panel.editors[("marker",)].widget
        texts = [combo.itemText(i) for i in range(combo.count())]
        combo.activated.emit(texts.index(text))

    panel.ask_marker = lambda current: "$\\alpha$"
    choose("Custom…")
    assert document.figure.axes[0].artists[0].marker == "$\\alpha$"
    assert panel.editors[("marker",)].widget.currentText() == "$\\alpha$"
    panel.ask_marker = lambda current: None  # cancelled
    choose("Custom…")
    assert document.figure.axes[0].artists[0].marker == "$\\alpha$"
    panel.ask_marker = lambda current: "q"
    choose("Custom…")
    assert "'q' is not a marker" in panel.error
