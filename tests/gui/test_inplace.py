"""Texts edited where they are drawn: a double-click on an axis label, a
title, a legend entry or a note, typing, and Enter or Esc."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

from figscribe.commands import InsertItem, SetField
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.model import Annotation


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    win.preview.grab()  # drawn once, at the window's size
    return win


def _center(window: MainWindow, text) -> QPointF:
    """Where the Matplotlib text `text` is drawn, in the preview."""
    preview = window.preview
    box = text.get_window_extent(preview._figure.canvas.get_renderer())
    corner = preview._to_widget(box.x0, box.y1)
    other = preview._to_widget(box.x1, box.y0)
    return (corner + other) / 2


def _ax(window: MainWindow):
    return window.preview._figure.axes[0]


def _double_click(window: MainWindow, point: QPointF):
    QTest.mouseDClick(
        window.preview,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        point.toPoint(),
    )
    return QApplication.focusWidget()


def _panel(window: MainWindow):
    return window.document.figure.axes[0]


def test_an_axis_label_is_edited_without_its_unit(window: MainWindow) -> None:
    field = _double_click(window, _center(window, _ax(window).xaxis.label))
    assert isinstance(field, QLineEdit)
    assert field.text() == "$t$"  # drawn as "t (s)"
    assert field.selectedText() == "$t$"
    QTest.keyClicks(field, "time")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert _panel(window).x.label == "time"
    assert _panel(window).x.unit == "s"
    assert window.document.history.undo_text == "Edit the label"


def test_esc_leaves_the_text_as_it_was(window: MainWindow) -> None:
    before = window.document.history.undo_text
    field = _double_click(window, _center(window, _ax(window).yaxis.label))
    QTest.keyClicks(field, "nothing")
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert _panel(window).y.label == "$U$"
    assert window.document.history.undo_text == before
    assert not field.isVisible()


def test_a_title_and_a_legend_entry(window: MainWindow) -> None:
    window.document.push(SetField(_panel(window).id, ("title",), "Scan"))
    field = _double_click(window, _center(window, _ax(window).title))
    QTest.keyClicks(field, "Calibration")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert _panel(window).title == "Calibration"

    entry = _ax(window).get_legend().get_texts()[0]
    field = _double_click(window, _center(window, entry))
    assert field.text() == "measurement"
    QTest.keyClicks(field, "data")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert _panel(window).artists[0].label == "data"


def test_an_emptied_legend_entry_leaves_the_legend(window: MainWindow) -> None:
    entry = _ax(window).get_legend().get_texts()[0]
    field = _double_click(window, _center(window, entry))
    QTest.keyClick(field, Qt.Key.Key_Delete)
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert _panel(window).artists[0].label is None


def test_a_note_keeps_its_lines(window: MainWindow) -> None:
    note = Annotation(text="peak", position=(0.2, 0.8), coords="axes")
    window.document.push(InsertItem(_panel(window).id, "artists", note))
    drawn = next(t for t in _ax(window).texts if t.get_gid() == note.id)
    field = _double_click(window, _center(window, drawn))
    assert isinstance(field, QPlainTextEdit)
    QTest.keyClicks(field, "peak")
    QTest.keyClick(field, Qt.Key.Key_Return)
    QTest.keyClicks(field, "at 5 s")
    QTest.keyClick(field, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert _panel(window).artists[-1].text == "peak\nat 5 s"
    assert window.document.history.undo_text == "Edit the note"


def test_a_double_click_elsewhere_edits_nothing(window: MainWindow) -> None:
    box = _ax(window).bbox
    inside = window.preview._to_widget(box.x0 + 5, box.y0 + 5)
    assert window.preview.text_at(inside) is None
    _double_click(window, inside)
    assert not window.preview.findChildren(QLineEdit)
