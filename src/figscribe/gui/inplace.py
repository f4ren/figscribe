"""Editing a text where it is drawn: a double-click on an axis label, a
panel's title, a legend entry or a note opens a field over it.

Enter (Ctrl+Enter for a note, which may have several lines) or leaving the
field sets the text, one undo step; Esc leaves it as it was.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QLineEdit, QWidget

from figscribe.gui.widgets import TextBox

Path = tuple[str, ...]


@dataclass
class Editable:
    """A text drawn in the preview that the model holds."""

    oid: str
    """The object that holds it."""
    path: Path
    """Where in that object, e.g. ("x", "label") of a panel."""
    text: str
    """What the model holds, which may differ from what is drawn: an axis
    label is drawn with its unit."""
    rect: QRectF
    """Where it is drawn, in the preview's coordinates."""
    lines: bool = False
    """Whether it may have several lines, as a note may."""


class _Line(QLineEdit):
    done = Signal(object)
    """The text when finished, or None when given up with Esc."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._finished = False
        self.returnPressed.connect(self._finish)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self._finish(cancel=True)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().focusOutEvent(event)
        self._finish()

    def _finish(self, cancel: bool = False) -> None:
        if self._finished:
            return
        self._finished = True
        self.done.emit(None if cancel else self.text())


class _Lines(TextBox):
    done = Signal(object)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._closed = False
        self.finished.connect(self._finish)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self._finish(cancel=True)
            return
        super().keyPressEvent(event)

    def _finish(self, cancel: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        self.done.emit(None if cancel else self.toPlainText())


MIN_WIDTH = 120
"""Logical pixels: a short label still gets a field one can type in."""


def open_editor(
    parent: QWidget, editable: Editable, done: Callable[[str | None], None]
) -> QWidget:
    """A field over `editable`'s text in `parent`, holding it all selected;
    `done` gets the new text, or None when given up."""
    editor = _Lines(parent) if editable.lines else _Line(parent)
    rect = editable.rect
    width = max(rect.width() + 24, MIN_WIDTH)
    if editable.lines:
        editor.setPlainText(editable.text)
        editor.selectAll()
        height = max(rect.height() + 16, 56)
    else:
        editor.setText(editable.text)
        editor.selectAll()
        height = editor.sizeHint().height()
    left = rect.center().x() - width / 2
    top = rect.center().y() - height / 2
    left = min(max(left, 0), max(parent.width() - width, 0))
    editor.setGeometry(int(left), int(top), int(width), int(height))
    editor.setObjectName("inPlace")

    def finish(text) -> None:
        editor.hide()
        editor.deleteLater()
        done(text)

    editor.done.connect(finish)
    editor.show()
    editor.setFocus(Qt.FocusReason.MouseFocusReason)
    return editor
