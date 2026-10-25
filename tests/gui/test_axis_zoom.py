"""Over an axis, inside the frame drawn around it when it is selected, the
wheel zooms and dragging pans that axis alone."""

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


def _in_frame_between_numbers(preview: Preview, field: str) -> QPointF:
    """A point inside the axis' selection frame that is on none of its
    numbers, its label or its edge: the gaps a person aims at too."""
    oid = axis_id(preview.document.figure.axes[0].id, field)
    preview.document.select(oid)
    frame = preview.selection_rect()
    for i in range(1, 40):
        for j in range(1, 10):
            point = QPointF(
                frame.left() + frame.width() * i / 40,
                frame.top() + frame.height() * j / 10,
            )
            if preview.axis_at(point) is None and preview.axes_at(point) is None:
                return point
    raise AssertionError("no gap in the frame")


def _limits(preview: Preview):
    ax = next(a for a in preview._figure.axes if a.get_gid())
    return {"x": ax.get_xlim(), "y": ax.get_ylim()}


@pytest.mark.parametrize(("field", "other"), [("x", "y"), ("y", "x")])
def test_the_wheel_anywhere_in_the_axis_frame_zooms_that_axis(
    preview: Preview, field: str, other: str
) -> None:
    point = _in_frame_between_numbers(preview, field)
    before = _limits(preview)
    _wheel(preview, point)
    after = _limits(preview)
    assert after[field] != pytest.approx(before[field])
    assert after[other] == pytest.approx(before[other])


@pytest.mark.parametrize(("field", "other"), [("x", "y"), ("y", "x")])
def test_dragging_in_the_axis_frame_pans_that_axis(
    qtbot, preview: Preview, field: str, other: str
) -> None:
    start = _in_frame_between_numbers(preview, field).toPoint()
    preview.document.select(None)
    before = _limits(preview)
    end = start + QPoint(40, 30)
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(preview, end)
    qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=end)
    after = _limits(preview)
    assert after[field] != pytest.approx(before[field])
    assert after[other] == pytest.approx(before[other])
    assert preview.document.selected is None  # a drag selects nothing
