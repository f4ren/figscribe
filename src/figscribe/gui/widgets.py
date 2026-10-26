"""Small building blocks shared by the panels."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLayout,
    QLayoutItem,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class FlowLayout(QLayout):
    """Lays its items out in rows, wrapping like words in a paragraph."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt naming
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._place(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


def chip(text: str, parent: QWidget | None = None) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("chip")
    return label


def rule() -> QFrame:
    """A thin line between the parts of a dialog."""
    line = QFrame()
    line.setObjectName("rule")
    line.setFixedHeight(1)
    return line


def label(text: str, name: str, parent: QWidget | None = None) -> QLabel:
    """A QLabel the style sheet knows by `name` (caption, kicker, ...)."""
    widget = QLabel(text, parent)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    return widget


class Section(QWidget):
    """A titled group of controls; optionally folds away behind its title."""

    def __init__(
        self,
        title: str,
        collapsible: bool = False,
        expanded: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("section")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)
        if collapsible:
            self.header = QToolButton()
            self.header.setObjectName("sectionToggle")
            self.header.setText(title)
            self.header.setCheckable(True)
            self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.header.toggled.connect(self._fold)
        else:
            self.header = label(title, "sectionTitle")
        layout.addWidget(self.header)
        self.body = QWidget()
        layout.addWidget(self.body)
        if collapsible:
            self.header.setChecked(expanded)
            self._fold(expanded)

    @property
    def expanded(self) -> bool:
        return not self.body.isHidden()

    def _fold(self, open_: bool) -> None:
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow
        )
        self.body.setVisible(open_)


class TextBox(QPlainTextEdit):
    """Text over several lines that says when it is done: on leaving the field,
    or with Ctrl+Enter (Cmd+Enter on macOS), since Enter starts a new line."""

    finished = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.finished.emit()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().focusOutEvent(event)
        self.finished.emit()
