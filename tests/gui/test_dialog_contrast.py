"""Every button of a dialog can be read, whether or not it has the focus.

A button with the focus becomes the dialog's default, and the style sheet's
rule for default buttons writes white text; a button whose own rule gives it a
pale ground and no color of its own then vanished (the fit dialog's models).
A new button style goes through this test without being listed."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton, QToolButton

from .legible import readable
from .test_small_screens import _make


@pytest.mark.parametrize("name", ["fit", "import", "plot", "assistant"])
def test_every_button_can_be_read_with_and_without_the_focus(
    qtbot, themed, example: Path, name: str
) -> None:
    dialog = _make(name, example)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitActive(dialog)
    buttons = [
        b
        for b in dialog.findChildren(QPushButton) + dialog.findChildren(QToolButton)
        if b.isVisibleTo(dialog) and b.isEnabled() and b.width() >= 20
    ]
    assert buttons
    faint = []
    for button in buttons:
        for focused in (False, True):
            if focused:
                button.setFocus()
                qtbot.waitUntil(button.hasFocus)
            if readable(button) < 4.5:
                label = button.text() or button.objectName()
                faint.append(f"{label!r} {'with' if focused else 'without'} focus")
    assert not faint, f"{name}: " + ", ".join(faint)
