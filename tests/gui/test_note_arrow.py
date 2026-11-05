"""The arrow of a note is set from the preview (U12): right-click the note to
give it one, then right-click where it should point; no typing of coordinates."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF

from figscribe.commands import SetField
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.model import Annotation


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _note(window: MainWindow) -> Annotation:
    window.ask_text = lambda title, prompt: "peak"
    window.note_action.trigger()
    return window.document.figure.axes[0].artists[-1]


def _text(window: MainWindow, note: Annotation):
    window.preview.grab()
    (text,) = [
        t
        for ax in window.preview._figure.axes
        for t in ax.texts
        if t.get_gid() == note.id
    ]
    return text


def _on_note(window: MainWindow, note: Annotation) -> QPointF:
    box = _text(window, note).get_window_extent()
    return window.preview._to_widget((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)


def _in_panel(window: MainWindow, fx: float, fy: float, panel: int = 0) -> QPointF:
    """The spot at fractions (fx, fy) of the panel, in widget coordinates."""
    window.preview.grab()
    box = window.preview._figure.axes[panel].bbox
    return window.preview._to_widget(box.x0 + fx * box.width, box.y0 + fy * box.height)


def _entry(menu, text: str):
    return next((a for a in menu.actions() if a.text() == text), None)


def _current(window: MainWindow, note: Annotation) -> Annotation:
    return next(a for a in window.document.figure.axes[0].artists if a.id == note.id)


def test_a_note_without_an_arrow_offers_one_on_a_right_click(window) -> None:
    note = _note(window)
    assert note.arrow_to is None
    menu = window.preview.context_menu(_on_note(window, note))
    assert _entry(menu, "Remove the note's arrow") is None
    _entry(menu, "Add an arrow").trigger()
    arrow = _current(window, note).arrow_to
    assert arrow is not None
    assert all(0 <= v <= 1 for v in arrow), "the tip is inside the panel"
    assert arrow != note.position
    assert window.document.history.undo_text == "Add an arrow"
    assert window.document.selected == note.id
    assert _text(window, note).arrow_patch is not None
    assert window.errors == [] and window.preview.error is None
    window.document.undo()
    assert _current(window, note).arrow_to is None


def test_a_selected_note_is_pointed_where_the_right_click_is(window) -> None:
    note = _note(window)
    spot = _in_panel(window, 0.2, 0.25)
    menu = window.preview.context_menu(spot)
    entry = _entry(menu, "Point the note's arrow here")
    assert entry is not None and entry.isEnabled()
    entry.trigger()
    arrow = _current(window, note).arrow_to
    assert arrow == pytest.approx((0.2, 0.25), abs=0.002)
    assert window.document.history.undo_text == "Point the note's arrow"
    # and again, somewhere else: the tip moves, one step each
    _entry(
        window.preview.context_menu(_in_panel(window, 0.8, 0.7)),
        "Point the note's arrow here",
    ).trigger()
    assert _current(window, note).arrow_to == pytest.approx((0.8, 0.7), abs=0.002)
    window.document.undo()
    assert _current(window, note).arrow_to == pytest.approx((0.2, 0.25), abs=0.002)


def test_a_note_in_data_coordinates_is_pointed_in_data_coordinates(window) -> None:
    note = _note(window)
    window.document.push(SetField(note.id, ("coords",), "data"))
    window.document.select(note.id)
    spot = _in_panel(window, 0.3, 0.4)
    _entry(window.preview.context_menu(spot), "Point the note's arrow here").trigger()
    arrow = _current(window, note).arrow_to
    ax = window.preview._figure.axes[0]
    box = ax.bbox
    x, y = ax.transData.transform(arrow)
    assert x == pytest.approx(box.x0 + 0.3 * box.width, abs=2)
    assert y == pytest.approx(box.y0 + 0.4 * box.height, abs=2)


def test_the_arrow_can_be_taken_away(window) -> None:
    note = _note(window)
    _entry(
        window.preview.context_menu(_in_panel(window, 0.2, 0.25)),
        "Point the note's arrow here",
    ).trigger()
    menu = window.preview.context_menu(_on_note(window, note))
    assert _entry(menu, "Add an arrow") is None
    _entry(menu, "Remove the note's arrow").trigger()
    assert _current(window, note).arrow_to is None
    assert window.document.history.undo_text == "Remove the note's arrow"
    window.document.undo()
    assert _current(window, note).arrow_to is not None


def test_nothing_is_offered_without_a_selected_note(window) -> None:
    _note(window)
    window.document.select(window.document.figure.axes[0].id)
    menu = window.preview.context_menu(_in_panel(window, 0.2, 0.25))
    texts = [a.text() for a in menu.actions()]
    assert not any("arrow" in t for t in texts), texts


def test_another_panel_cannot_be_pointed_at(window) -> None:
    note = _note(window)
    window.add_panel("right")
    window.document.select(note.id)
    menu = window.preview.context_menu(_in_panel(window, 0.5, 0.5, panel=1))
    texts = [a.text() for a in menu.actions()]
    assert "Point the note's arrow here" not in texts, texts
    here = window.preview.context_menu(_in_panel(window, 0.2, 0.25, panel=0))
    assert _entry(here, "Point the note's arrow here") is not None
