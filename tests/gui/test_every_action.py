"""Every action of the main window, triggered once in a fresh window on a
project that has every kind of object (`everything.py`).

The actions are found on the window, not listed here, so a new one is in the
test without anyone adding it. Dialogs are answered as a person in a hurry
would: files are chosen in the test's folder, questions get "Yes", dialogs
are accepted as proposed. An action may refuse with a message, but never
with an error that figscribe calls a bug, and nothing may reach Qt's event
loop as an exception (pytest-qt fails the test on that).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox

from figscribe.assistant import endpoint
from figscribe.commands import SetField
from figscribe.gui import Document, MainWindow
from figscribe.model import dumps

from .everything import build

BUG = "This is a bug in figscribe"
"""How `gui/errors.explain` starts a message about an unforeseen error."""


@pytest.fixture
def window_factory(qtbot, tmp_path: Path, monkeypatch):
    """Windows on the project, with every dialog answered; and the messages
    they showed."""
    project = build(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv(endpoint.ENV_DIR, str(tmp_path / "state"))
    shown: list[str] = []

    def message(parent, title, text, *args, **kwargs):
        shown.append(f"{title}: {text}")
        return QMessageBox.StandardButton.Ok

    def open_file(parent, caption, *args, **kwargs):
        chosen = tmp_path / "scan.csv" if "data" in caption.lower() else project
        return str(chosen), ""

    def save_file(parent, caption, *args, **kwargs):
        caption = caption.lower()
        name = "script.py" if "script" in caption else "figure.pdf"
        return str(out / ("saved.figscribe" if "project" in caption else name)), ""

    monkeypatch.setattr(QMessageBox, "warning", message)
    monkeypatch.setattr(QMessageBox, "information", message)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_file)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_file)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("A note", True))
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)

    def make() -> MainWindow:
        window = MainWindow(Document.open(project))
        qtbot.addWidget(window)
        window.show()
        document = window.document
        for name in ("Changed", "Changed again"):  # something to undo and redo
            document.push(SetField(document.figure.id, ("name",), name))
        document.undo()
        document.select(document.figure.axes[0].artists[0].id)  # the error bars
        return window

    return make, shown


def _actions(window: MainWindow) -> list[QAction]:
    """The window's menu actions, each once, in menu order."""
    found: list[QAction] = []
    for menu_action in window.menuBar().actions():
        for action in _in_menu(menu_action.menu()):
            if action not in found:
                found.append(action)
    return found


def _in_menu(menu) -> list[QAction]:
    actions = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        if action.menu() is not None:
            actions += _in_menu(action.menu())
        else:
            actions.append(action)
    return actions


@pytest.mark.slow
def test_every_action_works(qtbot, window_factory) -> None:
    make, shown = window_factory
    names = [action.text() for action in _actions(make())]
    assert len(names) > 20  # the menus were found
    problems = []
    for index, name in enumerate(names):
        window = make()
        action = _actions(window)[index]
        assert action.text() == name
        shown.clear()
        if not action.isEnabled():
            problems.append(f"{name.replace('&', '')}: off, so not tried")
            continue
        action.trigger()
        qtbot.wait(10)
        bugs = [text for text in shown if BUG in text]
        if bugs:
            problems.append(f"{name.replace('&', '')}: {bugs[0]}")
        window.close()
    assert not problems, "\n".join(problems)


@pytest.mark.slow
def test_every_entry_of_the_outline_menus_works(qtbot, window_factory) -> None:
    """Right-click on each object in the outline, and each entry once; what an
    entry changed is undone before the next."""
    make, shown = window_factory
    window = make()
    document = window.document
    project = document.project  # the same object throughout: undo restores it
    ids = [axes.id for axes in project.figures[0].axes] + [
        artist.id for axes in project.figures[0].axes for artist in axes.artists
    ]
    tried, problems = 0, []
    for oid in [project.figures[0].id, *ids, *(s.id for s in project.sources)]:
        menu = window.outline.context_menu(oid)
        entries = (
            [a.text() for a in menu.actions() if not a.isSeparator()] if menu else []
        )
        for text in entries:
            before = dumps(document.project)
            document.select(oid)
            shown.clear()
            entry = next(
                a
                for a in window.outline.context_menu(oid).actions()
                if a.text() == text
            )
            entry.trigger()
            qtbot.wait(10)
            tried += 1
            bugs = [message for message in shown if BUG in message]
            if bugs:
                problems.append(f"{oid} {text}: {bugs[0]}")
            while dumps(document.project) != before and document.history.can_undo:
                document.undo()
    assert tried > 20  # the menus were found
    assert not problems, "\n".join(problems)
