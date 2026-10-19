"""The Python code drawer under the preview."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from figscribe.commands import SetField
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.model import ColumnRef


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.show()
    qtbot.waitExposed(win)
    return win


def test_the_drawer_shows_the_script(window: MainWindow) -> None:
    assert window.code.isHidden()
    window.code_action.trigger()
    assert window.code.isVisible()
    text = window.code.text.toPlainText()
    assert "t, U, dU = np.loadtxt(scan_path" in text
    assert 'ax.set_xlabel("$t$ (s)")' in text
    window.code_action.trigger()
    assert window.code.isHidden()


def test_it_follows_every_change(qtbot, window: MainWindow) -> None:
    window.code_action.trigger()
    axes = window.document.figure.axes[0]
    window.document.push(SetField(axes.id, ("x", "label"), "time"))
    qtbot.waitUntil(lambda: '"time (s)"' in window.code.text.toPlainText())


def test_nothing_is_written_while_closed(window: MainWindow, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(window.code, "update_now", lambda: calls.append(1))
    window.document.push(SetField(window.document.figure.id, ("name",), "Other"))
    assert not window.code._timer.isActive() and calls == []


def test_copy_and_problems(window: MainWindow) -> None:
    window.code_action.trigger()
    window.code.copy.click()
    assert QApplication.clipboard().text().startswith('"""Scan')

    plot = window.document.figure.axes[0].artists[0]
    gone = ColumnRef(source="gone", column="U")
    window.document.push(SetField(plot.id, ("y",), gone))
    window.code.update_now()
    assert window.code.text.toPlainText().startswith("# The script cannot be written")
