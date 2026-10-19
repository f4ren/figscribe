"""The main window: outline, preview and problems around one Document."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from figscribe.assistant.toolserver import ToolServer
from figscribe.commands import CommandError, InsertItem, remove_artist, remove_axes
from figscribe.commands.core import walk
from figscribe.gui.document import Document
from figscribe.gui.importdialog import ImportDialog
from figscribe.gui.outline import Outline
from figscribe.gui.plotdialog import PlotDialog, add_plot
from figscribe.gui.preview import Preview
from figscribe.gui.problems import Problems
from figscribe.gui.properties import PropertyPanel
from figscribe.model import ArtistBase, Axes
from figscribe.render import export

MCP_HELP = """\
<p>An MCP client (Claude Desktop, Claude Code, an IDE, a local model's front
end) can change the open project through figscribe's tools. Every change
appears here at once and can be undone.</p>
<p>Install the MCP part once: <code>pip install "figscribe[mcp]"</code></p>
<p>Then add figscribe to the client. Claude Code:</p>
<pre>claude mcp add figscribe -- figscribe mcp</pre>
<p>Clients with a JSON configuration (e.g. Claude Desktop):</p>
<pre>{"mcpServers": {"figscribe": {"command": "figscribe", "args": ["mcp"]}}}</pre>
<p>The client sees the project's structure and column names, never the data,
unless you also allow it to see the figure.</p>"""

PROJECT_FILTER = "figscribe projects (*.figscribe)"
DATA_FILTER = "Delimited text (*.csv *.tsv *.txt *.dat);;All files (*)"
EXPORT_FILTER = "PDF (*.pdf);;SVG (*.svg);;PNG (*.png)"


class MainWindow(QMainWindow):
    def __init__(
        self,
        document: Document | None = None,
        parent: QWidget | None = None,
        settings: QSettings | None = None,
    ):
        super().__init__(parent)
        self.document = document or Document()
        self.settings = settings
        """Remembers the assistant switches; None (tests) remembers nothing."""
        self.tool_server = ToolServer(lambda: self.document, self)
        self.tool_server.clients_changed.connect(self._show_clients)
        self.tool_server.tool_called.connect(
            lambda name: self.statusBar().showMessage(f"Assistant: {name}", 3000)
        )
        self.ask: Callable[[str, str], bool] = self._ask_user
        """Asks a yes/no question; replaced in tests."""
        self.run_dialog: Callable[[QDialog], bool] = self._run_dialog
        """Runs a dialog, True if accepted; replaced in tests."""

        self.preview = Preview(self.document)
        self.setCentralWidget(self.preview)
        self.outline = Outline(self.document)
        self.problems = Problems(self.document)
        self.properties = PropertyPanel(self.document)
        project = self._dock(
            "Project", self.outline, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        properties = self._dock(
            "Properties", self.properties, Qt.DockWidgetArea.RightDockWidgetArea
        )
        problems = self._dock(
            "Problems", self.problems, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.resizeDocks([project, properties], [230, 320], Qt.Orientation.Horizontal)
        self.resizeDocks([problems], [90], Qt.Orientation.Vertical)

        self._build_menus()
        self._connect(self.document)
        self.resize(1100, 720)
        if self._setting("assistant/preview"):
            self.preview_action.setChecked(True)
        if self._setting("assistant/mcp"):
            self.mcp_action.setChecked(True)

    # --- assistant ------------------------------------------------------------

    def set_mcp_enabled(self, on: bool) -> None:
        """Let MCP clients reach the open project, or stop them."""
        if on and not self.tool_server.listening:
            try:
                self.tool_server.start()
            except OSError as exc:
                self.show_error("Cannot open the MCP connection", exc)
                self.mcp_action.setChecked(False)
                return
        elif not on and self.tool_server.listening:
            self.tool_server.stop()
        self._remember("assistant/mcp", on)
        self._show_clients(0)

    def set_preview_allowed(self, on: bool) -> None:
        """Whether tools may return an image of the figure, which shows the data."""
        self.document.allow_preview = on
        self._remember("assistant/preview", on)

    def _show_clients(self, count: int) -> None:
        if not self.tool_server.listening:
            self.statusBar().clearMessage()
            self._mcp_status.setText("")
            return
        clients = "no client" if count == 0 else f"{count} client(s)"
        self._mcp_status.setText(f"MCP: {clients} connected")

    def _setting(self, key: str) -> bool:
        if self.settings is None:
            return False
        return self.settings.value(key, False, type=bool)

    def _remember(self, key: str, value: bool) -> None:
        if self.settings is not None:
            self.settings.setValue(key, value)

    def _show_mcp_help(self) -> None:
        QMessageBox.information(self, "Connecting an assistant", MCP_HELP)

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

    # --- insert actions -----------------------------------------------------

    def import_csv(self, path: str | Path | None = None) -> None:
        """Add a delimited text file as a data source, asking how to read it."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import data", "", DATA_FILTER)
            if not path:
                return
        try:
            dialog = ImportDialog(path, self.document.project_dir, self)
        except OSError as exc:
            self.show_error(f"Cannot read {path}", exc)
            return
        if self.run_dialog(dialog) and dialog.source() is not None:
            source = dialog.source()
            self._push(InsertItem(None, "sources", source))
            self.document.select(source.id)

    def add_plot(self) -> None:
        """Add a plot of the data's columns to the selected axes."""
        columns = self.document.column_choices()
        figure = self.document.figure
        if not columns or figure is None:
            self.show_error("Nothing to plot", ValueError("Import a data file first."))
            return
        dialog = PlotDialog(columns, self)
        if not self.run_dialog(dialog):
            return
        artist = dialog.artist()
        self._push(add_plot(figure, self._target_axes(figure), artist))
        self.document.select(artist.id)

    def _target_axes(self, figure) -> str | None:
        """The selected axes, the axes of the selected plot, or the first one."""
        selected = self.document.selected
        for axes in figure.axes:
            if axes.id == selected or any(a.id == selected for a in axes.artists):
                return axes.id
        return figure.axes[0].id if figure.axes else None

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
        document.allow_preview = self.document.allow_preview
        self.document = document
        for view in (self.preview, self.outline, self.problems, self.properties):
            view.set_document(document)
        self._connect(document)

    def show_error(self, title: str, error: Exception) -> None:
        QMessageBox.warning(self, title, str(error))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        if not self.confirm_discard():
            event.ignore()
            return
        if self.tool_server.listening:
            self.tool_server.stop()
        event.accept()

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

    def _run_dialog(self, dialog: QDialog) -> bool:
        return dialog.exec() == QDialog.DialogCode.Accepted

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

        insert = self.menuBar().addMenu("&Insert")
        self._action(insert, "&Import Data…", lambda: self.import_csv(), "Ctrl+I")
        self._action(insert, "Add &Plot…", self.add_plot, "Ctrl+Shift+P")

        assistant = self.menuBar().addMenu("&Assistant")
        self.mcp_action = self._toggle(
            assistant, "Allow &MCP Access", self.set_mcp_enabled
        )
        self.preview_action = self._toggle(
            assistant, "Let It See the &Figure", self.set_preview_allowed
        )
        assistant.addSeparator()
        self._action(assistant, "&How to Connect…", self._show_mcp_help)
        self._mcp_status = QLabel()
        self.statusBar().addPermanentWidget(self._mcp_status)

    def _toggle(self, menu, text: str, slot) -> QAction:
        """A checkable action; `slot` runs on every change, also from code."""
        action = QAction(text, self)
        action.setCheckable(True)
        action.toggled.connect(slot)
        menu.addAction(action)
        return action

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
