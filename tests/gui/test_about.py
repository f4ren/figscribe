"""Help > About figscribe: which version is running, for bug reports."""

from __future__ import annotations

import platform
from pathlib import Path

import matplotlib
import PySide6
import pytest
from PySide6.QtCore import qVersion
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMessageBox

import figscribe
from figscribe.gui import MainWindow
from figscribe.gui.about import about_text
from figscribe.gui.app import create_window


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    return win


def _help_menu(window: MainWindow):
    return next(a.menu() for a in window.menuBar().actions() if a.text() == "&Help")


def test_the_text_names_the_versions_a_bug_report_needs() -> None:
    text = about_text()
    assert f"figscribe {figscribe.__version__}" in text
    assert platform.python_version() in text
    assert matplotlib.__version__ in text
    assert PySide6.__version__ in text
    assert qVersion() in text
    assert platform.system() in text
    assert "github.com/f4ren/figscribe" in text


def test_the_help_menu_is_the_last_and_has_about(window: MainWindow) -> None:
    menus = [a.text() for a in window.menuBar().actions()]
    assert menus[-1] == "&Help"
    assert window.about_action in _help_menu(window).actions()
    assert window.about_action.text() == "&About figscribe"


def test_about_stays_in_the_help_menu_on_macos(window: MainWindow) -> None:
    # Qt would move an "About …" entry into the application menu on macOS
    # and leave Help empty; the user looks for the version under Help.
    assert window.about_action.menuRole() == QAction.MenuRole.NoRole


def test_about_shows_the_version(window: MainWindow, monkeypatch) -> None:
    shown = []
    monkeypatch.setattr(
        QMessageBox, "about", lambda parent, title, text: shown.append((title, text))
    )
    window.about_action.trigger()
    ((title, text),) = shown
    assert title == "About figscribe"
    assert figscribe.__version__ in text


def test_about_can_be_found_in_the_palette(window: MainWindow) -> None:
    from figscribe.gui.palette import matching, menu_entries

    entries = matching(menu_entries(window.menuBar()), "about")
    assert [e.where for e in entries if e.text == "About figscribe"] == ["Help"]


def test_the_application_knows_its_version(qtbot) -> None:
    from figscribe.gui.app import set_application_identity

    set_application_identity(QApplication.instance())
    assert QApplication.applicationVersion() == figscribe.__version__
    assert QApplication.applicationName() == "figscribe"
