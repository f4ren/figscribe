"""The command palette (Ctrl+K): every menu action and every setting of the
selection, found by typing a few letters of it.

An entry is a line of text, where it is found, and what choosing it does.
Typed words must all occur in the entry or in its keywords, the words a person
might use for it (a "band" for a shaded range); entries whose text starts with
the first word come first, then those that have the words in their name, then
those found by a keyword only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

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
    hold: list = field(default_factory=list, repr=False, compare=False)
    """Qt objects `run` depends on, kept so that they stay valid: see
    `menu_entries`."""
    keywords: str = ""
    """Other words for it, found by typing but not shown; see `KEYWORDS`."""


KEYWORDS = {
    # menu actions
    "Import Data…": "csv load open file table npz npy",
    "Add Figure": "tab page",
    "Add Plot…": "chart graph curve",
    "Line": "curve trace line plot",
    "Points": "scatter markers dots",
    "Error bars": "errorbar uncertainty yerr sigma",
    "Histogram": "bins distribution frequency counts",
    "Allan deviation": "adev stability oscillator noise tau",
    "Image": "picture matrix pixels imshow 2d",
    "Color mesh": "heatmap colormap colour map pcolormesh 2d surface",
    "Add Fit…": "regression residuals least squares model curve fit",
    "Add Note…": "annotation text label callout arrow pointer comment",
    "Vertical line": "reference threshold marker guide rule",
    "Horizontal line": "reference threshold marker guide rule",
    "Shaded x range": "band region highlight interval window span shade",
    "Shaded y range": "band region highlight interval window span shade",
    "Panel to the right": "subplot axes next to",
    "Panel to the left": "subplot axes next to",
    "Panel above": "subplot axes",
    "Panel below": "subplot axes residuals",
    "Inset": "subplot zoom magnifier inside",
    # settings
    "Arrow to": "arrow pointer tip",
    "Fewer points": "reduce downsample average mean bin thin decimate",
    "Error band": "ribbon confidence uncertainty fill",
    "Line style": "dashed dotted solid linestyle",
    "Grid lines": "gridlines grid",
    "Right y axis": "secondary second twin axis",
    "Color map": "colormap cmap viridis palette",
    "Normalize to density": "density normalise pdf",
    "Bins (count, or edges)": "histogram binning",
    "Panel labels": "letters subpanel",
    "Ticks on all sides": "mirror ticks",
    "Units in labels": "unit format brackets slash",
    "Why left out": "outlier exclude omit",
    "Left-out color": "outlier exclude omit",
    "Left-out marker": "outlier exclude omit",
    "Legend entry": "label name legend",
}
"""Words to find an entry by besides its text, by its text. A kind of element
that an example uses is tested to be found (`tests/gui/test_find_words.py`)."""


AXIS_KEYWORDS = {
    # (section, caption) of the axis form
    ("Label", "Label"): "title name text xlabel ylabel",
    ("Label", "Unit"): "units si",
    ("Label", "Show values in"): "prefix si milli kilo mega micro factor power",
    ("Label", "Label size (pt)"): "font text",
    ("Label", "Label distance (pt)"): "labelpad padding spacing gap",
    ("Scale", "Type"): "log logarithmic symlog symmetric linear scale semilog loglog",
    ("Scale", "From"): "range limits limit xlim ylim min max bounds extent zoom",
    ("Scale", "Linear within ±"): "symlog linthresh threshold",
    ("Scale", "Number size (pt)"): "tick label font numbers",
    ("Ticks", "Major ticks"): "tick spacing step interval positions locator labels",
    ("Ticks", "Distance"): "tick spacing step interval",
    ("Ticks", "Values"): "tick positions locations",
    ("Ticks", "Tick labels"): "names text categories custom",
    ("Ticks", "Minor ticks"): "subdivisions between",
}
"""The same for the rows of the axis form, whose captions are short ("Type",
"From") because the section says what they are about."""


def words_for(caption: str, section: str) -> str:
    """The other words for a setting: its own, or those of its caption."""
    return AXIS_KEYWORDS.get((section, caption)) or KEYWORDS.get(caption, "")


def menu_entries(bar: QMenuBar) -> list[Entry]:
    """Every enabled action of the menu bar, with the menus it is in.

    PySide6 before 6.12 makes the wrapper of a menu invalid, and with it the
    wrappers of its actions, as soon as the wrapper of the action that holds
    the menu is gone: running an entry of a submenu raised "Internal C++
    object already deleted". So every menu and action visited is kept in a
    list that each entry holds on to.
    """
    found: list[Entry] = []
    hold: list = []

    def walk(menu: QMenu, path: list[str]) -> None:
        hold.append(menu)
        for action in menu.actions():
            hold.append(action)
            if action.isSeparator() or not action.isVisible():
                continue
            text = action.text().replace("&", "")
            submenu = action.menu()
            if submenu is not None:
                walk(submenu, [*path, text])
            elif action.isEnabled():
                found.append(
                    Entry(
                        text,
                        " › ".join(path),
                        action.trigger,
                        hold,
                        KEYWORDS.get(text, ""),
                    )
                )

    for action in bar.actions():
        hold.append(action)
        submenu = action.menu()
        if submenu is not None:
            walk(submenu, [action.text().replace("&", "")])
    return found


def matching(entries: list[Entry], query: str) -> list[Entry]:
    """The entries that have every word of `query`, best first."""
    words = query.lower().split()
    if not words:
        return list(entries)

    def named(e: Entry) -> bool:
        return all(w in f"{e.text} {e.where}".lower() for w in words)

    def rank(e: Entry) -> int:
        if e.text.lower().startswith(words[0]):
            return 0
        return 1 if named(e) else 2

    found = [
        e
        for e in entries
        if all(w in f"{e.text} {e.where} {e.keywords}".lower() for w in words)
    ]
    return sorted(found, key=rank)


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
