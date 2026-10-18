"""The project outline: sources, figures, their axes and artists as a tree."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from figscribe.gui.document import Document
from figscribe.model import Axes, Figure

ID_ROLE = Qt.ItemDataRole.UserRole


class Outline(QTreeWidget):
    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self._syncing = False
        self.itemSelectionChanged.connect(self._on_tree_selection)
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(self.rebuild)
        document.selection_changed.connect(self._show_selection)
        self.rebuild()

    def rebuild(self) -> None:
        self._syncing = True
        try:
            self.clear()
            project = self.document.project
            if project.sources:
                sources = QTreeWidgetItem(self, ["Data"])
                for source in project.sources:
                    _item(sources, source.path, source.id)
            for figure in project.figures:
                _figure_item(self, figure)
            self.expandAll()
        finally:
            self._syncing = False
        self._show_selection(self.document.selected)

    def item_for(self, oid: str) -> QTreeWidgetItem | None:
        for item in _walk(self.invisibleRootItem()):
            if item.data(0, ID_ROLE) == oid:
                return item
        return None

    def _on_tree_selection(self) -> None:
        if self._syncing:
            return
        items = self.selectedItems()
        self.document.select(items[0].data(0, ID_ROLE) if items else None)

    def _show_selection(self, oid: str | None) -> None:
        self._syncing = True
        try:
            item = self.item_for(oid) if oid is not None else None
            self.setCurrentItem(item) if item else self.clearSelection()
        finally:
            self._syncing = False


def _figure_item(parent: QTreeWidget, figure: Figure) -> None:
    item = _item(
        parent,
        f"{figure.name} ({figure.width_mm:g} × {figure.height_mm:g} mm)",
        figure.id,
    )
    for axes in figure.axes:
        _axes_item(item, axes)


def _axes_item(parent: QTreeWidgetItem, axes: Axes) -> None:
    where = f"row {axes.row}, col {axes.col}"
    name = f"Axes: {axes.title}" if axes.title else "Axes"
    item = _item(parent, f"{name} ({where})", axes.id)
    for artist in axes.artists:
        label = f"{artist.kind}: {artist.label}" if artist.label else artist.kind
        _item(item, label, artist.id)


def _item(parent, text: str, oid: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem(parent, [text])
    item.setData(0, ID_ROLE, oid)
    return item


def _walk(item: QTreeWidgetItem):
    for i in range(item.childCount()):
        child = item.child(i)
        yield child
        yield from _walk(child)
