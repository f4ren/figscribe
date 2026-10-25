"""The wheel over an axis' numbers or label zooms only that axis."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from figscribe.gui import Document
from figscribe.gui.document import axis_id
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


def _over_numbers(preview: Preview, field: str) -> QPointF:
    """The middle of the axis' numbers, in widget coordinates."""
    oid = axis_id(preview.document.figure.axes[0].id, field)
    boxes = next(b for a, b in preview._axis_boxes() if a == oid)
    numbers = boxes[len(boxes) // 2]  # one of the tick labels
    return preview._to_widget(
        (numbers.x0 + numbers.x1) / 2, (numbers.y0 + numbers.y1) / 2
    )


def _wheel(preview: Preview, point: QPointF) -> None:
    preview.wheelEvent(
        QWheelEvent(
            point,
            preview.mapToGlobal(point),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
    )


@pytest.mark.parametrize(("field", "other"), [("x", "y"), ("y", "x")])
def test_the_wheel_over_an_axis_zooms_only_that_axis(
    preview: Preview, field: str, other: str
) -> None:
    ax = next(a for a in preview._figure.axes if a.get_gid())
    before = {"x": ax.get_xlim(), "y": ax.get_ylim()}
    _wheel(preview, _over_numbers(preview, field))
    assert preview.view
    after = {"x": ax.get_xlim(), "y": ax.get_ylim()}
    low, high = sorted(after[field])
    assert high - low < abs(before[field][1] - before[field][0])  # zoomed in
    assert after[other] == pytest.approx(before[other])
