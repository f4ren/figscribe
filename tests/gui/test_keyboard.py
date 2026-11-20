"""Keyboard only: Tab reaches every control of a dialog and its accept button,
and Escape leaves. B7.5 of the roadmap.

On macOS, Tab moves only between text fields and lists unless the system's
"Keyboard navigation" is on (System Settings > Keyboard), which no offscreen
test sees; the manual checklist asks for that setting to be switched on."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QWidget,
)

from figscribe.gui import Document
from figscribe.gui.fitdialog import FitDialog
from figscribe.gui.importdialog import ImportDialog


def _inputs(dialog: QDialog) -> list[QWidget]:
    """What a person operates: enabled, shown, and willing to take the focus."""
    kinds = (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit)
    return [
        w
        for w in dialog.findChildren(QWidget)
        if isinstance(w, kinds)
        and w.isVisibleTo(dialog)
        and w.isEnabled()
        and w.focusPolicy() & Qt.FocusPolicy.TabFocus
        and not (isinstance(w.parent(), QAbstractSpinBox | QComboBox))
    ]


def _tabbed(dialog: QDialog) -> list[QWidget]:
    """The widgets that get the focus, in order, from one Tab after another until
    the first comes round again."""
    dialog.activateWindow()
    seen: list[QWidget] = []
    for _ in range(200):
        QTest.keyClick(dialog, Qt.Key.Key_Tab)
        focus = dialog.focusWidget()
        if seen and focus is seen[0]:
            return seen
        if focus is not None:
            seen.append(focus)
    raise AssertionError("Tab never comes round")


@pytest.fixture
def dialogs(qtbot, themed, example: Path):
    document = Document.open(example)
    made = {
        "fit": FitDialog(document.figure.axes[0].artists[0], document.data),
        "import": ImportDialog(example.parent / "scan.csv", example.parent),
    }
    for dialog in made.values():
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitActive(dialog)
    return made


@pytest.mark.parametrize("name", ["fit", "import"])
def test_tab_reaches_every_control_and_the_accept_button(dialogs, name: str) -> None:
    dialog = dialogs[name]
    reached = _tabbed(dialog)
    missed = [
        f"{type(w).__name__} {w.objectName() or getattr(w, 'text', lambda: '')()!r}"
        for w in _inputs(dialog)
        if w not in reached
    ]
    assert not missed, f"Tab never reaches: {', '.join(missed)}"
    accept = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert accept in reached


@pytest.mark.parametrize("name", ["fit", "import"])
def test_escape_leaves_and_nothing_is_added(dialogs, name: str) -> None:
    dialog = dialogs[name]
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    # FitDialog keeps its fit in `result`, which hides QDialog's
    assert not dialog.isVisible()
    assert QDialog.result(dialog) == QDialog.DialogCode.Rejected
