"""Every button of a dialog can be read, whether or not it has the focus.

A button with the focus becomes the dialog's default, and the style sheet's
rule for default buttons writes white text; a button whose own rule gives it a
pale ground and no color of its own then vanished (the fit dialog's models).
A new button style goes through this test without being listed."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

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


@pytest.mark.parametrize(
    "make",
    [
        lambda: QCheckBox("Draw the points outside like left-out ones"),
        lambda: QDoubleSpinBox(),
        lambda: QSpinBox(),
        lambda: QLineEdit("text"),
        lambda: QComboBox(),
        lambda: QLabel("a label"),
    ],
    ids=["check box", "double spin box", "spin box", "line edit", "combo box", "label"],
)
def test_a_disabled_control_looks_disabled(qtbot, themed, make) -> None:
    """The style sheet greys fields and captions that do nothing (B8.4); a
    control it did not name looked as if it still worked."""
    host = QWidget()
    qtbot.addWidget(host)
    control = make()
    if isinstance(control, QComboBox):
        control.addItem("an entry")
    if isinstance(control, QAbstractSpinBox):
        control.setValue(7)
    QVBoxLayout(host).addWidget(control)
    host.show()
    enabled = readable(control)
    control.setEnabled(False)
    assert readable(control) < enabled * 0.5
