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


def test_the_left_out_marker_is_chosen_with_buttons(qtbot, preview: Preview) -> None:
    from figscribe.commands import SetField
    from figscribe.gui.properties import MarkerEditor, PropertyPanel

    document = preview.document
    plot = document.figure.axes[0].artists[0]
    document.push(SetField(plot.id, ("left_out",), [12]))
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    document.select(plot.id)
    editor = panel.editors[("left_out_marker",)]
    assert isinstance(editor, MarkerEditor)
    assert editor.buttons[None].toolTip() == "The plot's marker"
    editor.buttons["s"].click()
    assert document.figure.axes[0].artists[0].left_out_marker == "s"
    panel.editors[("left_out_marker",)].buttons[None].click()
    assert document.figure.axes[0].artists[0].left_out_marker is None
