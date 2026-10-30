"""Reference lines and shaded ranges, added from the menus and the preview."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.markings import marking
from figscribe.model import ReferenceLine, ShadedSpan


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    win.preview.grab()  # drawn once, so the shown ranges are known
    return win


@pytest.mark.parametrize(
    ("kind", "low", "high", "at", "expected"),
    [
        ("refline", 0.0, 10.0, None, 5.0),
        ("refline", -0.05, 1.05, None, 0.5),
        ("refline", 0.0, 10.0, 4.2371, 4.2),
        ("refline", 1e-3, 1e3, None, 1.0),  # the middle of a log axis
        ("span", 0.0, 10.0, None, (4.0, 6.0)),
        ("span", 0.0, 10.0, 7.03, (6.0, 8.0)),
        ("span", 1e-3, 1e3, None, (0.25, 4.0)),
    ],
)
def test_a_marking_lands_on_a_round_value(kind, low, high, at, expected) -> None:
    log = low == 1e-3
    made = marking(kind, "vertical", low, high, log=log, at=at)
    if kind == "refline":
        assert isinstance(made, ReferenceLine) and made.at == expected
    else:
        assert isinstance(made, ShadedSpan)
        assert (made.start, made.end) == pytest.approx(expected, rel=0.02)


def _action(window: MainWindow, text: str):
    return next(a for a in window.marking_menu.actions() if a.text() == text)


def test_the_insert_menu_adds_lines_and_ranges(window: MainWindow) -> None:
    document = window.document
    panel = document.figure.axes[0]
    low, high = window.preview.axis_limits(f"{panel.id}/x")
    _action(window, "Vertical line").trigger()
    line = document.figure.axes[0].artists[-1]
    assert isinstance(line, ReferenceLine) and line.orientation == "vertical"
    assert low < line.at < high
    assert abs(line.at - (low + high) / 2) <= (high - low) / 100
    assert document.selected == line.id
    assert document.history.undo_text == "Add a vertical line"
    assert window.outline.item_for(line.id).text(0) == f"Line at x = {line.at:g}"
    _action(window, "Shaded y range").trigger()
    span = document.figure.axes[0].artists[-1]
    assert isinstance(span, ShadedSpan) and span.orientation == "horizontal"
    assert window.preview.error is None and window.errors == []
    document.undo()
    document.undo()
    assert document.figure.axes[0].artists == panel.artists[: len(panel.artists)]
    assert not any(
        isinstance(a, ReferenceLine | ShadedSpan)
        for a in document.figure.axes[0].artists
    )


def test_the_outline_offers_them_on_a_panel(window: MainWindow) -> None:
    panel = window.document.figure.axes[0]
    menu = window.outline.context_menu(panel.id)
    # Each wrapper is kept in a name: PySide6 before 6.12 makes a menu invalid
    # once the wrapper of the action that holds it is gone.
    actions = menu.actions()
    (lines,) = [a for a in actions if a.menu() is not None]
    sub = lines.menu()
    entries = sub.actions()
    entry = next(a for a in entries if a.text() == "Horizontal line")
    entry.trigger()
    line = window.document.figure.axes[0].artists[-1]
    assert isinstance(line, ReferenceLine) and line.orientation == "horizontal"


def test_right_clicking_the_preview_adds_one_where_clicked(window: MainWindow) -> None:
    preview = window.preview
    document = window.document
    ax = next(
        a for a in preview._figure.axes if a.get_gid() == document.figure.axes[0].id
    )
    # Away from the points: three quarters along x, near the bottom.
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    x, y = x0 + 0.75 * (x1 - x0), y0 + 0.05 * (y1 - y0)
    point = preview._to_widget(*ax.transData.transform((x, y)))
    menu = preview.context_menu(point)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert not any(t.startswith("Leave out") for t in texts)
    entry = next(a for a in menu.actions() if a.text().startswith("Vertical line at x"))
    entry.trigger()
    line = document.figure.axes[0].artists[-1]
    assert isinstance(line, ReferenceLine)
    assert line.at == pytest.approx(x, abs=(x1 - x0) / 100)
    assert entry.text() == f"Vertical line at x = {line.at:g}"
    assert document.selected == line.id
    menu = preview.context_menu(point)
    next(a for a in menu.actions() if a.text() == "Shade an x range here").trigger()
    span = document.figure.axes[0].artists[-1]
    assert isinstance(span, ShadedSpan) and span.start < x < span.end
