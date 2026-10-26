"""Resizing in the preview: an inset by a corner, the grid by a gap; one
undo step on release."""

from __future__ import annotations

from pathlib import Path

import pytest
from matplotlib.transforms import Bbox
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from figscribe.commands import add_panel
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.resize import Corner, Gap, bounds, ratios


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    win.resize(1300, 900)
    win.show()
    qtbot.waitExposed(win)
    return win


def _add(window: MainWindow, side: str) -> str:
    document = window.document
    command, new = add_panel(document.project, document.figure.axes[0].id, side)
    document.push(command)
    window.preview.grab()
    return new.id


def _drag(window: MainWindow, start: QPointF, end: QPointF) -> None:
    preview = window.preview
    left = Qt.MouseButton.LeftButton
    QTest.mousePress(preview, left, Qt.KeyboardModifier.NoModifier, start.toPoint())
    middle = (start + end) / 2
    QTest.mouseMove(preview, middle.toPoint())
    QTest.mouseMove(preview, end.toPoint())
    QTest.mouseRelease(preview, left, Qt.KeyboardModifier.NoModifier, end.toPoint())


def _box(window: MainWindow, oid: str):
    return window.preview._boxes()[oid]


def test_dragging_an_inset_corner_resizes_it(window: MainWindow) -> None:
    inset = _add(window, "inset")
    document = window.document
    before = find_bounds(window, inset)
    box = _box(window, inset)
    corner = window.preview._to_widget(box.x1, box.y1)  # upper right
    assert isinstance(window.preview.handle_at(corner), Corner)
    _drag(window, corner, corner + QPointF(40, -30))
    after = find_bounds(window, inset)
    assert after[0] == pytest.approx(before[0], abs=0.01)  # the lower left stays
    assert after[1] == pytest.approx(before[1], abs=0.01)
    assert after[2] > before[2] and after[3] > before[3]
    assert document.history.undo_text == "Resize the inset"
    document.undo()
    assert find_bounds(window, inset) == before


def find_bounds(window: MainWindow, oid: str):
    return next(a for a in window.document.figure.axes if a.id == oid).inset.bounds


def test_dragging_the_gap_between_columns_changes_their_widths(
    window: MainWindow,
) -> None:
    _add(window, "right")
    document = window.document
    gap = next(
        h for h in _gaps(window) if isinstance(h, Gap) and h.field == "width_ratios"
    )
    low, high = gap.extent
    start = window.preview._to_widget(gap.middle, (low + high) / 2)
    assert isinstance(window.preview.handle_at(start), Gap)
    _drag(window, start, start + QPointF(60, 0))
    widths = document.figure.layout.width_ratios
    assert widths is not None and widths[0] > widths[1]
    assert sum(widths) == pytest.approx(2.0)
    assert document.history.undo_text == "Resize the columns"


def test_dragging_the_gap_between_rows_changes_their_heights(
    window: MainWindow,
) -> None:
    _add(window, "below")
    document = window.document
    gap = next(h for h in _gaps(window) if h.field == "height_ratios")
    low, high = gap.extent
    start = window.preview._to_widget((low + high) / 2, gap.middle)
    _drag(window, start, start + QPointF(0, -40))  # up: the upper row shrinks
    heights = document.figure.layout.height_ratios
    assert heights is not None and heights[0] < heights[1]
    assert document.history.undo_text == "Resize the rows"


def _gaps(window: MainWindow):
    from figscribe.gui.resize import gaps

    return gaps(window.document.figure, window.preview._boxes())


def test_the_cursor_says_what_a_drag_resizes(window: MainWindow) -> None:
    inset = _add(window, "inset")
    box = _box(window, inset)
    QTest.mouseMove(window.preview, window.preview._to_widget(box.x0, box.y1).toPoint())
    assert window.preview.cursor().shape() == Qt.CursorShape.SizeFDiagCursor
    QTest.mouseMove(window.preview, QPointF(5, 5).toPoint())
    assert window.preview.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_click_on_a_gap_still_selects(window: MainWindow) -> None:
    _add(window, "right")
    gap = next(h for h in _gaps(window) if h.field == "width_ratios")
    low, high = gap.extent
    point = window.preview._to_widget(gap.middle, (low + high) / 2)
    before = window.document.figure.layout.width_ratios
    QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert window.document.figure.layout.width_ratios == before


def test_bounds_keep_the_opposite_corner_and_a_smallest_size() -> None:
    parent = Bbox([[0, 0], [100, 100]])
    inset = Bbox([[50, 50], [80, 80]])
    assert bounds(parent, inset, "upper right", 90, 95) == (0.5, 0.5, 0.4, 0.45)
    assert bounds(parent, inset, "lower left", 10, 20) == (0.1, 0.2, 0.7, 0.6)
    tiny = bounds(parent, inset, "upper right", 50.5, 50.5)
    assert tiny[2:] == (0.05, 0.05)


def test_ratios_keep_the_sum_of_the_two_and_a_least_share() -> None:
    gap = Gap("width_ratios", 0, 50, (0, 10), (0, 100))
    assert ratios(None, 3, gap, 75) == [1.5, 0.5, 1.0]
    assert ratios([2.0, 2.0], 2, gap, 0) == [0.4, 3.6]
