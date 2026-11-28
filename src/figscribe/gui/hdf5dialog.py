"""Adding data of an HDF5 file (decision 0081)."""

from __future__ import annotations

import re
from collections import Counter

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QFormLayout, QHeaderView, QTreeWidget, QTreeWidgetItem

from figscribe.gui import theme
from figscribe.gui.importdialog import PREVIEW_ROWS, DataDialog
from figscribe.io.hdf5file import Entry, entries, hdf5_source, head, likely, units
from figscribe.model import Hdf5Source
from figscribe.suggest import Suggestion, suggest

PREVIEW_COLUMNS = 50
"""Columns the preview shows of data in two dimensions."""
OPEN_AT_ONCE = 60
"""Up to this many entries the tree is shown unfolded."""

X_NAMES = re.compile(
    r"(t|x|f|time|freq|frequency|wavelength|energy)([_ .\[(].*)?", re.IGNORECASE
)
"""Names of what the others are usually measured against."""


class Hdf5Dialog(DataDialog):
    """Asks which group or dataset of `path` to read (see `DataDialog`)."""

    def _settings_form(self, form: QFormLayout) -> None:
        self._entries = {e.path: e for e in entries(self._raw, self.path.name)}
        self._first = likely(list(self._entries.values()), self.path.name).path
        self.tree = QTreeWidget()
        self.tree.setObjectName("dataTree")
        self.tree.setHeaderLabels(["In the file", "Holds"])
        self.tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tree.setAccessibleName("Groups and datasets of the file")
        self.tree.setMinimumHeight(190)
        self.items: dict[str, QTreeWidgetItem] = {}
        """{path: its row in the tree}."""
        for path, entry in self._entries.items():
            self.items[path] = self._item(path, entry)
        if len(self.items) <= OPEN_AT_ONCE:
            self.tree.expandAll()
        else:
            self.tree.expandToDepth(0)
        form.addRow(self.tree)

    def _item(self, path: str, entry: Entry) -> QTreeWidgetItem:
        if path == "/":
            item = QTreeWidgetItem(self.tree, ["/", _holds(entry)])
        else:
            above, name = path.rsplit("/", 1)
            item = QTreeWidgetItem(self.items[above or "/"], [name, _holds(entry)])
        item.setToolTip(0, path)
        item.setToolTip(1, entry.problem or _holds(entry))
        if entry.problem:  # shown, and what is inside can be chosen
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for column in (0, 1):
                item.setForeground(column, QBrush(QColor(theme.MUTED)))
        return item

    def _start(self) -> None:
        self.resize(980, 720)  # the tree, and the table below it
        self.detected.hide()  # nothing is guessed that a chip could change
        self.settings.show()  # choosing the data is what the dialog is for
        self.tree.setCurrentItem(self.items[self._first])
        self.tree.scrollToItem(self.items[self._first])
        self.tree.currentItemChanged.connect(lambda *_: self.update_preview())

    def _chosen(self) -> Entry:
        path = self.tree.currentItem().toolTip(0)
        return self._entries[path]

    def _read(self) -> tuple[Hdf5Source, np.ndarray]:
        source = hdf5_source(
            self.path, self.base_dir or self.path.parent, dataset=self._chosen().path
        )
        source = self._relative_to_project(source)
        columns, self._width = head(source, self._raw, PREVIEW_ROWS, PREVIEW_COLUMNS)
        self._head = dict(zip(source.columns, columns, strict=False))
        rows = max((len(values) for values in columns), default=0)
        # "" beside a column that ends before the others.
        table = np.full((rows, len(columns)), "", dtype=object)
        for i, values in enumerate(columns):
            table[: len(values), i] = [float(v) for v in values]
        return source, table

    def _size(self, source: Hdf5Source, table: np.ndarray) -> tuple[int, int]:
        return source.row_count, self._width

    def _advice(self) -> str:
        return "Not the data you meant? Choose another entry of the file."

    def _read_units(self, source: Hdf5Source, count: int) -> list[str] | None:
        found = units(source, self._raw) if source.columns else []
        return found if any(found) else None

    def _cell(self, value) -> str:
        return "" if isinstance(value, str) else f"{value:g}"

    def _numbers_note(self, source: Hdf5Source, table: np.ndarray) -> list[str]:
        entry = self._entries[source.dataset]
        notes = []
        if entry.left_out:
            what = ", ".join(f"{n} ({why})" for n, why in entry.left_out.items())
            notes.append(f"Left out: {what}.")
        if len(set(entry.lengths)) > 1:
            notes.append(
                "The columns have different lengths; only those of one length can "
                "be plotted against each other."
            )
        return notes

    def _chip_texts(self) -> list[str]:
        return []

    def _plottable(self) -> list[str | int] | None:
        """For a group of columns of different lengths, those of the commonest
        one: a first plot must be of columns that go together."""
        if self._source is None or self._source.holds != "group":
            return super()._plottable()
        entry = self._entries[self._source.dataset]
        common = Counter(entry.lengths).most_common(1)[0][0]
        return [
            name
            for name, length in zip(entry.columns, entry.lengths, strict=True)
            if length == common
        ]

    def _suggested(self) -> list[Suggestion]:
        if self._source is not None and self._source.holds == "image":
            name = self._source.dataset.rsplit("/", 1)[-1]
            return [Suggestion("image", "", name)]
        columns = self._plottable()
        return suggest(self._x_first(columns)) if columns else []

    def _x_first(self, columns: list[str]) -> list[str]:
        """The columns with the likely x in front: the file lists names by the
        alphabet, which says nothing about what is plotted against what."""

        def rises(name: str) -> bool:
            values = self._head.get(name)
            return values is not None and len(values) > 1 and all(np.diff(values) > 0)

        x = next((c for c in columns if X_NAMES.fullmatch(c)), None)
        x = x or next((c for c in columns if rises(c)), None)
        return columns if x is None else [x, *(c for c in columns if c != x)]


def _holds(entry: Entry) -> str:
    """What an entry gives, in a few words, or why it gives nothing."""
    if entry.problem:
        return entry.problem
    if entry.kind == "image":
        return f"{entry.shape[0]} × {entry.shape[1]} numbers"
    if entry.kind == "column":
        return f"{entry.rows} numbers"
    count = len(entry.columns)
    columns = f"{count} column{'s' if count != 1 else ''}"
    if entry.kind == "table":
        return f"{entry.rows} records, {columns}"
    return columns
