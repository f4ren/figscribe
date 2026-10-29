"""The command palette (Ctrl+K): every menu action and every setting of the
selection, found by typing a few letters of it.

An entry is a line of text, where it is found, and what choosing it does.
Typed words must all occur in the entry; entries whose text starts with the
first word come first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMenuBar,
    QVBoxLayout,
    QWidget,
)


@dataclass
class Entry:
    text: str
    """What it is called, e.g. "Add Plot…" or "Color"."""
    where: str
    """Where it is found, e.g. "Insert" or "Setting · Look"."""
    run: Callable[[], None]


def menu_entries(bar: QMenuBar) -> list[Entry]:
    """Every enabled action of the menu bar, with the menus it is in."""
    found: list[Entry] = []

    def walk(menu: QMenu, path: list[str]) -> None:
        for action in menu.actions():
            if action.isSeparator() or not action.isVisible():
                continue
            text = action.text().replace("&", "")
            if action.menu() is not None:
                walk(action.menu(), [*path, text])
            elif action.isEnabled():
                found.append(Entry(text, " › ".join(path), action.trigger))

    for action in bar.actions():
        if action.menu() is not None:
            walk(action.menu(), [action.text().replace("&", "")])
    return found


def matching(entries: list[Entry], query: str) -> list[Entry]:
    """The entries that have every word of `query`, best first."""
    words = query.lower().split()
    if not words:
        return list(entries)
    found = [
        e for e in entries if all(w in f"{e.text} {e.where}".lower() for w in words)
    ]
    return sorted(found, key=lambda e: not e.text.lower().startswith(words[0]))


class CommandPalette(QDialog):
    """A line to type in and the entries that match; Enter chooses the first,
    or the one moved to with the arrow keys. The window runs the chosen entry
    once the palette is closed, so that a dialog it opens is not inside it."""

    def __init__(self, entries: list[Entry], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("palette")
        self.setWindowTitle("Find a setting or action")
        self.setMinimumWidth(460)
        self.entries = entries
        self.line = QLineEdit()
        self.line.setPlaceholderText("Type a setting or an action, e.g. legend")
        self.line.textChanged.connect(self._show)
        self.line.installEventFilter(self)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._run)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.line)
        layout.addWidget(self.list)
        self._shown: list[Entry] = []
        self.chosen: Entry | None = None
        self._show("")

    def _show(self, query: str) -> None:
        self._shown = matching(self.entries, query)
        self.list.clear()
        for entry in self._shown:
            item = QListWidgetItem(f"{entry.text}    {entry.where}")
            item.setToolTip(entry.where)
            self.list.addItem(item)
        if self._shown:
            self.list.setCurrentRow(0)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        """Up and Down move through the entries while typing; Enter runs one."""
        if watched is self.line and isinstance(event, QKeyEvent):
            if event.type() == QKeyEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    step = 1 if key == Qt.Key.Key_Down else -1
                    row = self.list.currentRow() + step
                    if 0 <= row < self.list.count():
                        self.list.setCurrentRow(row)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._run(self.list.currentItem())
                    return True
        return super().eventFilter(watched, event)

    def _run(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        self.chosen = self._shown[self.list.row(item)]
        self.accept()
