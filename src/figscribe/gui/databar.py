"""The bar above the preview while a data file is not as it was imported.

One row per file that changed or went missing, each with what can be done
about it, and a line for every plot that uses a column its file no longer
has. Taking a file as it is now, or from where it moved, is one undo step.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.gui.document import Document
from figscribe.gui.names import artist_name
from figscribe.io import DataError
from figscribe.io.files import resolve_path
from figscribe.io.refresh import describe_change, reread, use_new_version
from figscribe.model import DataSource
from figscribe.model.validate import missing_columns


class DataBar(QWidget):
    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("dataBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(12, 6, 8, 6)
        self._rows.setSpacing(4)
        self.choose_file: Callable[[DataSource], Path | None] = self._choose_file
        """Asks where a missing file went; replaced in tests."""
        self.show_message: Callable[[str, str], None] = self._show_message
        """Shows a few lines of text; replaced in tests."""
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        """Look at the files again and show what is not as imported."""
        while self._rows.count():
            row = self._rows.takeAt(0).widget()
            row.hide()
            row.setParent(None)
            row.deleteLater()  # the row's own button may be what asked for this
        project = self.document.project
        sources = {source.id: source for source in project.sources}
        for source_id, state in self.document.data_states().items():
            self._file_row(sources[source_id], state)
        for artist, _, column in missing_columns(project):
            name = Path(sources[column.source].path).name
            self._row(
                f"{artist_name(artist)} uses the column {column.column}, "
                f"which {name} does not have."
            )
        # Qt shows a child added to a visible widget only when told, and each
        # row is shown once complete, its buttons with it.
        for i in range(self._rows.count()):
            self._rows.itemAt(i).widget().show()
        self.setVisible(self._rows.count() > 0)

    def _file_row(self, source: DataSource, state: str) -> None:
        name = Path(source.path).name
        if state == "missing":
            where = resolve_path(source.path, self.document.base_dir)
            row = self._row(f"{name} is missing: it is no longer at {where}.")
            self._button(row, "Locate file…", lambda: self._locate(source))
        else:
            row = self._row(f"{name} has changed since it was imported.")
            self._button(row, "Show what changed", lambda: self._show_change(source))
            self._button(
                row, "Use the new version", lambda: self._use(source), primary=True
            )

    def _row(self, text: str) -> QHBoxLayout:
        widget = QWidget(self)
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        message = QLabel(text)
        message.setWordWrap(True)
        row.addWidget(message, 1)
        self._rows.addWidget(widget)
        return row

    def _button(
        self, row: QHBoxLayout, text: str, action: Callable[[], None], primary=False
    ) -> None:
        button = QPushButton(text)
        if primary:
            button.setObjectName("primary")
        button.clicked.connect(action)
        row.addWidget(button)

    # --- actions ----------------------------------------------------------------

    def _use(self, source: DataSource, path: Path | None = None) -> None:
        try:
            command = use_new_version(
                self.document.project, source.id, self.document.base_dir, path
            )
        except DataError as exc:
            self.show_message("The file cannot be used", str(exc))
            return
        self.document.push(command)

    def _locate(self, source: DataSource) -> None:
        path = self.choose_file(source)
        if path is not None:
            self._use(source, path)

    def _show_change(self, source: DataSource) -> None:
        name = Path(source.path).name
        try:
            new = reread(source, self.document.base_dir)
        except DataError as exc:
            self.show_message(f"What changed in {name}", str(exc))
            return
        self.show_message(f"What changed in {name}", describe_change(source, new))

    def _choose_file(self, source: DataSource) -> Path | None:
        name = Path(source.path).name
        chosen, _ = QFileDialog.getOpenFileName(
            self, f"Locate {name}", str(self.document.base_dir), f"{name} (*)"
        )
        return Path(chosen) if chosen else None

    def _show_message(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)
