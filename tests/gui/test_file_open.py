"""A project opened from the file manager: on macOS the system does not put its
name on the command line but sends the running program an event."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window, install_file_open


@pytest.fixture
def window(qtbot) -> MainWindow:
    win = create_window([])  # the start page, as after a double click on the app
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    return win


def _send(path: Path) -> None:
    QApplication.sendEvent(
        QApplication.instance(), QFileOpenEvent(QUrl.fromLocalFile(str(path)))
    )


def test_the_system_asking_to_open_a_project_opens_it(
    window: MainWindow, example: Path
) -> None:
    install_file_open(QApplication.instance(), window)

    _send(example)

    assert window.document.path == example
    assert not window.on_start_page


def test_a_file_that_is_no_project_says_so_and_changes_nothing(
    window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    install_file_open(QApplication.instance(), window)
    shown = []
    monkeypatch.setattr(window, "show_error", lambda *args: shown.append(args))
    broken = tmp_path / "broken.figscribe"
    broken.write_text("not a project")

    _send(broken)

    assert shown
    assert window.document.path is None
