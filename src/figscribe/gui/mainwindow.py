"""The main window: outline, preview and problems around one Document."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from figscribe.commands import CommandError, remove_artist, remove_axes
from figscribe.commands.core import walk
from figscribe.gui.document import Document
from figscribe.gui.outline import Outline
from figscribe.gui.preview import Preview
from figscribe.gui.problems import Problems
from figscribe.model import ArtistBase, Axes
from figscribe.render import export

PROJECT_FILTER = "figscribe projects (*.figscribe)"
EXPORT_FILTER = "PDF (*.pdf);;SVG (*.svg);;PNG (*.png)"


class MainWindow(QMainWindow):
    def __init__(self, document: Document | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.document = document or Document()
        self.ask: Callable[[str, str], bool] = self._ask_user
        """Asks a yes/no question; replaced in tests."""

        self.preview = Preview(self.document)
        self.setCentralWidget(self.preview)
        self.outline = Outline(self.document)
        self.problems = Problems(self.document)
        self._dock("Project", self.outline, Qt.DockWidgetArea.LeftDockWidgetArea)
        problems = self._dock(
            "Problems", self.problems, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.resizeDocks([problems], [90], Qt.Orientation.Vertical)

        self._build_menus()
        self._connect(self.document)
        self.resize(1100, 720)

    # --- file actions -------------------------------------------------------

    def new_project(self) -> None:
        if self.confirm_discard():
            self.set_document(Document())

    def open_path(self, path: str | Path) -> None:
        """Open a project file; errors are shown, the current project stays."""
        try:
            document = Document.open(path)
        except (OSError, ValueError) as exc:
            self.show_error(f"Cannot open {path}", exc)
            return
        self.set_document(document)

    def save(self) -> bool:
        if self.document.path is None:
            return self.save_as()
        return self._save_to(None)

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "", PROJECT_FILTER)
        if not path:
            return False
        if not path.endswith(".figscribe"):
            path += ".figscribe"
        return self._save_to(Path(path))

    def export_to(self, path: str | Path) -> None:
        figure = self.document.figure
        if figure is None:
            return
        try:
            export(figure, self.document.data, path)
        except Exception as exc:
            self.show_error(f"Cannot export to {path}", exc)

    def confirm_discard(self) -> bool:
        """True when the current project may be replaced or closed."""
        if self.document.history.is_clean:
            return True
        return self.ask("Unsaved changes", "Discard the unsaved changes?")

    # --- edit actions -------------------------------------------------------

    def delete_selected(self) -> None:
        """Remove the selected artist or axes, with what depends on it."""
        oid = self.document.selected
        for obj, _, field in walk(self.document.project):
            if obj.id != oid:
                continue
            if isinstance(obj, ArtistBase) and field == "artists":
                self._push(remove_artist(self.document.project, oid))
            elif isinstance(obj, Axes):
                self._push(remove_axes(self.document.project, oid))
            return

    def _push(self, command) -> None:
        try:
            self.document.push(command)
        except CommandError as exc:
            self.show_error("The change was refused", exc)

    # --- window -------------------------------------------------------------

    def set_document(self, document: Document) -> None:
        self.document = document
        for view in (self.preview, self.outline, self.problems):
            view.set_document(document)
        self._connect(document)

    def show_error(self, title: str, error: Exception) -> None:
        QMessageBox.warning(self, title, str(error))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        event.accept() if self.confirm_discard() else event.ignore()

    def _connect(self, document: Document) -> None:
        document.state_changed.connect(self._update_state)
        document.selection_changed.connect(self._update_state)
        self._update_state()

    def _update_state(self) -> None:
        history = self.document.history
        self.setWindowTitle(self.document.title)
        self.undo_action.setEnabled(history.can_undo)
        self.undo_action.setText(
            f"&Undo {history.undo_text}" if history.can_undo else "&Undo"
        )
        self.redo_action.setEnabled(history.can_redo)
        self.redo_action.setText(
            f"&Redo {history.redo_text}" if history.can_redo else "&Redo"
        )
        self.delete_action.setEnabled(self.document.selected is not None)

    def _save_to(self, path: Path | None) -> bool:
        try:
            self.document.save(path)
        except OSError as exc:
            self.show_error("Cannot save the project", exc)
            return False
        return True

    def _open_dialog(self) -> None:
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", PROJECT_FILTER)
        if path:
            self.open_path(path)

    def _export_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export figure", "", EXPORT_FILTER)
        if path:
            self.export_to(path)

    def _ask_user(self, title: str, question: str) -> bool:
        answer = QMessageBox.question(self, title, question)
        return answer == QMessageBox.StandardButton.Yes

    def _dock(
        self, title: str, widget: QWidget, area: Qt.DockWidgetArea
    ) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_menus(self) -> None:
        file = self.menuBar().addMenu("&File")
        self._action(file, "&New", self.new_project, QKeySequence.StandardKey.New)
        self._action(file, "&Open…", self._open_dialog, QKeySequence.StandardKey.Open)
        self._action(file, "&Save", self.save, QKeySequence.StandardKey.Save)
        self._action(file, "Save &As…", self.save_as, QKeySequence.StandardKey.SaveAs)
        file.addSeparator()
        self._action(file, "&Export Figure…", self._export_dialog, "Ctrl+E")
        file.addSeparator()
        self._action(file, "&Quit", self.close, QKeySequence.StandardKey.Quit)

        edit = self.menuBar().addMenu("&Edit")
        self.undo_action = self._action(
            edit, "&Undo", lambda: self.document.undo(), QKeySequence.StandardKey.Undo
        )
        self.redo_action = self._action(
            edit, "&Redo", lambda: self.document.redo(), QKeySequence.StandardKey.Redo
        )
        edit.addSeparator()
        self.delete_action = self._action(
            edit, "&Delete", self.delete_selected, QKeySequence.StandardKey.Delete
        )

    def _action(self, menu, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        # Also on the window, so the shortcut works while the menu bar is native
        # or hidden.
        self.addAction(action)
        return action
