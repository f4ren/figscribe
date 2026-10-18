"""The problem list: what validate_references finds, kept up to date."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from figscribe.gui.document import Document
from figscribe.model import validate_references

ID_ROLE = Qt.ItemDataRole.UserRole


class Problems(QListWidget):
    """Lists every cross-object issue; a click selects the object concerned."""

    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.itemClicked.connect(self._on_click)
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        self.clear()
        for issue in validate_references(self.document.project):
            item = QListWidgetItem(str(issue), self)
            item.setData(ID_ROLE, issue.object_id)

    def _on_click(self, item: QListWidgetItem) -> None:
        self.document.select(item.data(ID_ROLE))
