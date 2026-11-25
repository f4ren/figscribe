"""Help > Check for Updates…, clicked as a person does; never online."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

import figscribe
from figscribe import updates
from figscribe.gui import Document, MainWindow

PAGE = "https://github.com/f4ren/figscribe/releases/tag/v9.0.0"


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    widget = MainWindow(Document.open(example))
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def seen(monkeypatch) -> dict:
    """What the person is shown and what is opened; Open is answered."""
    seen: dict = {
        "messages": [],
        "opened": [],
        "answer": QMessageBox.StandardButton.Open,
    }

    def information(parent, title, text, *buttons):
        seen["messages"].append(("information", text, buttons))
        return seen["answer"]

    def warning(parent, title, text, *buttons):
        seen["messages"].append(("warning", text, buttons))

    monkeypatch.setattr(QMessageBox, "information", information)
    monkeypatch.setattr(QMessageBox, "warning", warning)
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: seen["opened"].append(url.toString())
    )
    return seen


def _latest(monkeypatch, version: str = "9.0.0") -> None:
    release = updates.Release(version, PAGE)
    monkeypatch.setattr(updates, "latest_release", lambda: release)


def _installed(monkeypatch, installed: bool) -> None:
    monkeypatch.setattr(sys, "frozen", installed, raising=False)


def test_the_entry_is_in_help_before_about_and_stays_there_on_macos(window) -> None:
    help_action = next(a for a in window.menuBar().actions() if a.text() == "&Help")
    menu = help_action.menu()
    texts = [a.text() for a in menu.actions()]
    assert texts.index("Check for &Updates…") < texts.index("&About figscribe")
    assert window.update_action.menuRole() == QAction.MenuRole.NoRole


def test_a_newer_version_is_named_and_its_page_opened(
    window, seen, monkeypatch
) -> None:
    _latest(monkeypatch)
    _installed(monkeypatch, True)
    window.update_action.trigger()
    ((kind, text, _),) = seen["messages"]
    assert kind == "information"
    assert "9.0.0" in text and figscribe.__version__ in text
    assert seen["opened"] == [PAGE]


def test_closing_the_message_opens_nothing(window, seen, monkeypatch) -> None:
    _latest(monkeypatch)
    _installed(monkeypatch, True)
    seen["answer"] = QMessageBox.StandardButton.Close
    window.update_action.trigger()
    assert seen["opened"] == []


def test_with_pip_the_upgrade_command_is_given(window, seen, monkeypatch) -> None:
    _latest(monkeypatch)
    _installed(monkeypatch, False)
    window.update_action.trigger()
    ((_, text, _),) = seen["messages"]
    assert "pip install --upgrade figscribe" in text
    assert seen["opened"] == []


def test_the_newest_version_is_said_to_be_the_newest(window, seen, monkeypatch) -> None:
    _latest(monkeypatch, figscribe.__version__)
    window.update_action.trigger()
    ((kind, text, _),) = seen["messages"]
    assert kind == "information" and "newest" in text
    assert seen["opened"] == []


def test_a_failure_is_a_warning_and_the_cursor_comes_back(
    window, seen, monkeypatch
) -> None:
    def fail():
        raise updates.UpdateError("figscribe could not reach GitHub.")

    monkeypatch.setattr(updates, "latest_release", fail)
    window.update_action.trigger()
    assert [m[:2] for m in seen["messages"]] == [
        ("warning", "figscribe could not reach GitHub.")
    ]
    assert QApplication.overrideCursor() is None
