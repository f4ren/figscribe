"""The main window: outline, preview and problems around one Document."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, QStandardPaths, Qt, QUrl
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.assistant.toolserver import ToolServer
from figscribe.codegen import generate, script_name
from figscribe.commands import (
    CommandError,
    InsertItem,
    Macro,
    SetField,
    add_panel,
    remove_artist,
    remove_axes,
)
from figscribe.commands.core import walk
from figscribe.fit import FitError, add_fit
from figscribe.gui import theme
from figscribe.gui.chatpanel import ChatPanel
from figscribe.gui.codepanel import CodePanel
from figscribe.gui.document import Document
from figscribe.gui.fitdialog import FitDialog
from figscribe.gui.importdialog import ImportDialog
from figscribe.gui.outline import PANEL_SIDES, Outline
from figscribe.gui.plotdialog import PlotDialog, add_plot
from figscribe.gui.preview import Preview
from figscribe.gui.problems import Problems
from figscribe.gui.properties import PropertyPanel
from figscribe.gui.start import DOCS_URL, StartPage, bundled_example
from figscribe.model import (
    Annotation,
    ArtistBase,
    Axes,
    AxisSpec,
    FitCurve,
    Histogram,
)
from figscribe.model.validate import FITTABLE
from figscribe.render import export
from figscribe.templates import template

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
SCRIPT_FILTER = "Python script (*.py)"
DATA_SUFFIXES = {".csv", ".tsv", ".txt", ".dat"}
START_FILTER = "Data or project (*.csv *.tsv *.txt *.dat *.figscribe);;All files (*)"
MAX_RECENT = 6


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
        self._recent: list[Path] = []
        self._worked = False
        """Whether the workspace was shown: the start page then offers a way back."""
        self.ask: Callable[[str, str], bool] = self._ask_user
        """Asks a yes/no question; replaced in tests."""
        self.run_dialog: Callable[[QDialog], bool] = self._run_dialog
        self.ask_text: Callable[[str, str], str | None] = self._ask_text
        """Asks for a line of text, None if cancelled; replaced in tests."""
        """Runs a dialog, True if accepted; replaced in tests."""

        self.preview = Preview(self.document)
        self.start = StartPage()
        self._connect_start(self.start)
        self.chat = ChatPanel(self.document)
        self.chat.hide()
        self.chat.busy_changed.connect(
            lambda busy: self.statusBar().showMessage(
                "Assistant at work…" if busy else ""
            )
        )
        self.code = CodePanel(self.document)
        self.code.save_requested.connect(self._script_dialog)
        self.code.hide()
        self.workspace = QSplitter(Qt.Orientation.Vertical)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.addWidget(self.preview)
        self.workspace.addWidget(self.chat)
        self.workspace.addWidget(self.code)
        self.workspace.setStretchFactor(0, 3)
        self.workspace.setStretchFactor(1, 2)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.start)
        self.pages.addWidget(self.workspace)
        self.pages.setCurrentWidget(self.workspace)
        self.setCentralWidget(self.pages)
        self.examples_dir = _documents() / "figscribe examples"
        """Where the example is copied to, so it can be edited and saved."""
        self.outline = Outline(self.document)
        self.problems = Problems(self.document)
        self.properties = PropertyPanel(self.document)
        self.outline.add_requested.connect(self._add_plot_to)
        self.outline.import_requested.connect(lambda: self.import_csv())
        self.outline.panel_requested.connect(
            lambda oid, side: self.add_panel(side, oid)
        )
        self.outline.delete_requested.connect(self._delete)
        self.outline.note_requested.connect(self.add_note)
        self.contents_dock = self._dock(
            "Contents", _side_panel(self.outline), Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.properties_dock = self._dock(
            "Properties", self.properties, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.problems_dock = self._dock(
            "Problems", self.problems, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.resizeDocks(
            [self.contents_dock, self.properties_dock],
            [260, 340],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks([self.problems_dock], [80], Qt.Orientation.Vertical)

        self._build_menus()
        self._build_toolbar()
        self.setAcceptDrops(True)
        self._connect(self.document)
        self.resize(1280, 800)
        if self._setting("view/code"):
            self.code_action.setChecked(True)
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

    def new_from_template(self, key: str) -> None:
        """Start a new project whose figure is the template's layout."""
        if not self.confirm_discard():
            return
        project = Document().project
        project.figures = [template(key).build()]
        self.set_document(Document(project))

    def open_path(self, path: str | Path) -> None:
        """Open a project file; errors are shown, the current project stays."""
        try:
            document = Document.open(path)
        except (OSError, ValueError) as exc:
            self.show_error(f"Cannot open {path}", exc)
            return
        self.set_document(document)
        self._add_recent(document.path)

    def open_example(self) -> None:
        """Open a copy of the example project that can be changed and saved."""
        if not self.confirm_discard():
            return
        target = self.examples_dir / "gaussian-scan"
        if not (target / "scan.figscribe").is_file():
            try:
                shutil.copytree(bundled_example(), target, dirs_exist_ok=True)
            except OSError as exc:
                self.show_error("Cannot copy the example", exc)
                return
        self.open_path(target / "scan.figscribe")

    # --- start page -----------------------------------------------------------

    @property
    def on_start_page(self) -> bool:
        return self.pages.currentWidget() is self.start

    def show_start(self) -> None:
        """Show the start page; the open project stays until it is replaced."""
        self.start.set_recent(self.recent)
        path = self.document.path
        name = path.stem if path is not None else "Untitled"
        self.start.set_back(name if self._worked else None)
        self.pages.setCurrentWidget(self.start)
        self._show_panels(False)

    def show_workspace(self) -> None:
        self._worked = True
        self.pages.setCurrentWidget(self.workspace)
        self._show_panels(True)

    def _show_panels(self, on: bool) -> None:
        self.toolbar.setVisible(on)
        self.contents_dock.setVisible(on)
        self.properties_dock.setVisible(on)
        self._show_problems()

    def _connect_start(self, start: StartPage) -> None:
        start.files_dropped.connect(self.open_dropped)
        start.choose_file.connect(self._choose_start_file)
        start.open_project.connect(self._open_dialog)
        start.template_chosen.connect(self.new_from_template)
        start.example_requested.connect(self.open_example)
        start.assistant_requested.connect(self._show_mcp_help)
        start.recent_chosen.connect(self._open_recent)
        start.back_requested.connect(self.show_workspace)
        start.docs_requested.connect(lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)))

    def _choose_start_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open", "", START_FILTER)
        if path:
            self.open_dropped([Path(path)])

    def _open_recent(self, path: Path) -> None:
        if self.confirm_discard():
            self.open_path(path)

    def _start_with_data(self, path: Path) -> None:
        """A new project around a data file; back to the start if cancelled."""
        if not self.confirm_discard():
            return
        self.new_from_template("single")
        if not self.import_csv(path):
            self.show_start()

    @property
    def recent(self) -> list[Path]:
        """Recently opened or saved projects, most recent first."""
        if self.settings is None:
            return list(self._recent)
        value = self.settings.value("recent", [])
        if isinstance(value, str):
            value = [value]
        return [Path(p) for p in value or []]

    def _add_recent(self, path: Path | None) -> None:
        if path is None:
            return
        path = path.resolve()
        paths = [path, *(p for p in self.recent if p != path)][:MAX_RECENT]
        self._recent = paths
        if self.settings is not None:
            self.settings.setValue("recent", [str(p) for p in paths])

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

    def export_script(self, path: str | Path) -> None:
        """Write the Python script that draws the shown figure to `path`."""
        figure = self.document.figure
        if figure is None:
            return
        path = Path(path)
        try:
            script = generate(
                self.document.project,
                figure,
                base_dir=self.document.base_dir,
                script_dir=path.parent,
                output=f"{path.stem}.pdf",
                data=self.document.data,
            )
            path.write_text(script, encoding="utf-8")
        except Exception as exc:
            self.show_error(f"Cannot write {path.name}", exc)

    def _script_dialog(self) -> None:
        figure = self.document.figure
        if figure is None:
            return
        folder = self.document.project_dir or Path.home()
        suggested = str(folder / script_name(figure))
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Python script", suggested, SCRIPT_FILTER
        )
        if path:
            self.export_script(path if path.endswith(".py") else f"{path}.py")

    def confirm_discard(self) -> bool:
        """True when the current project may be replaced or closed."""
        if self.document.history.is_clean:
            return True
        return self.ask("Unsaved changes", "Discard the unsaved changes?")

    # --- insert actions -----------------------------------------------------

    def import_csv(self, path: str | Path | None = None) -> bool:
        """Add a delimited text file as a data source, asking how to read it.

        True if a source was added.
        """
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Import data", "", DATA_FILTER)
            if not path:
                return False
        try:
            dialog = ImportDialog(path, self.document.project_dir, self)
        except OSError as exc:
            self.show_error(f"Cannot read {path}", exc)
            return False
        if not self.run_dialog(dialog) or dialog.source() is None:
            return False
        source = dialog.source()
        artist = dialog.planned_artist() if dialog.mode == "plot" else None
        figure = self.document.figure
        if artist is None or figure is None:
            self._push(InsertItem(None, "sources", source))
            self.document.select(source.id)
            if dialog.mode == "custom":
                self.add_plot()
            return True
        steps = [InsertItem(None, "sources", source)]
        steps += self._plot_steps(figure, artist, dialog)
        self._push(Macro(f"Add {Path(source.path).name} and plot", steps))
        self.document.select(artist.id)
        return True

    def _plot_steps(self, figure, artist, dialog) -> list:
        """Put `artist` into the target axes, naming its empty axes after the
        plotted columns and their units."""
        if isinstance(artist, Histogram):
            values = artist.values
            labels = {
                "x": AxisSpec(
                    label=str(values.column), unit=dialog.unit_of(values.column)
                ),
                "y": AxisSpec(label="Count"),
            }
        else:
            labels = {
                name: AxisSpec(label=str(ref.column), unit=dialog.unit_of(ref.column))
                for name, ref in (("x", artist.x), ("y", artist.y))
            }
        axes_id = self._target_axes(figure)
        if axes_id is None:
            axes = Axes(artists=[artist], **labels)
            return [InsertItem(figure.id, "axes", axes)]
        axes = next(a for a in figure.axes if a.id == axes_id)
        steps = [
            SetField(axes_id, (name,), spec)
            for name, spec in labels.items()
            if getattr(axes, name).label is None and not axes.artists
        ]
        return [*steps, InsertItem(axes_id, "artists", artist)]

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

    def add_fit(self) -> None:
        """Fit a model to the selected plot (or the only one) and add it."""
        target = self._fit_target()
        if target is None:
            self.show_error(
                "Nothing to fit", ValueError("Select the plot to fit, then try again.")
            )
            return
        figure = self.document.figure
        axes = next(a for a in figure.axes if target in a.artists)
        below = any(
            o.row == axes.row + axes.rowspan and o.col == axes.col and not o.artists
            for o in figure.axes
        )
        try:
            dialog = FitDialog(target, self.document.data, below, self)
        except Exception as exc:  # the data cannot be read
            self.show_error("Cannot fit", exc)
            return
        if not self.run_dialog(dialog) or dialog.fit() is None:
            return
        fit = dialog.fit()
        try:
            command = add_fit(self.document.project, fit, dialog.residuals.isChecked())
        except FitError as exc:
            self.show_error("Cannot fit", exc)
            return
        self._push(command)
        self.document.select(fit.id)

    def add_note(self, oid: str | None = None) -> None:
        """Add a note in the middle of a panel; drag it in the preview."""
        figure = self.document.figure
        if figure is None:
            return
        target = oid if oid is not None else self._target_axes(figure)
        if target is None:
            self.show_error("No panel", ValueError("Add a panel or a plot first."))
            return
        text = self.ask_text("Add note", "Text (LaTeX allowed, e.g. $\\mu$):")
        if not text:
            return
        note = Annotation(text=text, position=(0.5, 0.5), coords="axes")
        self._push(InsertItem(target, "artists", note))
        self.document.select(note.id)

    def _ask_text(self, title: str, prompt: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, prompt)
        return text.strip() if ok else None

    def _fit_target(self):
        figure = self.document.figure
        if figure is None:
            return None
        plots = [a for axes in figure.axes for a in axes.artists]
        selected = next((a for a in plots if a.id == self.document.selected), None)
        if isinstance(selected, FitCurve):
            selected = next((a for a in plots if a.id == selected.target), None)
        if isinstance(selected, FITTABLE):
            return selected
        fittable = [a for a in plots if isinstance(a, FITTABLE)]
        return fittable[0] if len(fittable) == 1 else None

    def add_panel(self, side: str, oid: str | None = None) -> None:
        """Add an empty panel beside or inside the panel `oid` (default: the
        selected one, or that of the selected plot, or the first)."""
        figure = self.document.figure
        if figure is None:
            return
        target = oid if oid is not None else self._target_axes(figure)
        axes = next((a for a in figure.axes if a.id == target), None)
        if axes is not None and axes.inset is not None:
            axes = next(a for a in figure.axes if a.id == axes.inset.parent)
        if axes is None:
            new = Axes()
            self._push(InsertItem(figure.id, "axes", new))
        else:
            try:
                command, new = add_panel(self.document.project, axes.id, side)
            except CommandError as exc:
                self.show_error("Cannot add the panel", exc)
                return
            self._push(command)
        self.document.select(new.id)

    def show_chat(self, on: bool) -> None:
        """Show or hide the built-in assistant under the preview."""
        self.chat.setVisible(on)
        if on:
            self.chat.input.setFocus()

    def show_code(self, on: bool) -> None:
        """Show or hide the Python code drawer under the preview."""
        self.code.setVisible(on)
        self._remember("view/code", on)

    def _delete(self, oid: str) -> None:
        self.document.select(oid)
        self.delete_selected()

    def _add_plot_to(self, oid: str) -> None:
        self.document.select(oid)
        self.add_plot()

    def open_dropped(self, paths: list[Path]) -> None:
        """Open a dropped project file, or add dropped data files."""
        for path in paths:
            if path.suffix == ".figscribe":
                if self.confirm_discard():
                    self.open_path(path)
                return
        data = [p for p in paths if p.suffix.lower() in DATA_SUFFIXES]
        if data and self.on_start_page:
            self._start_with_data(data.pop(0))
        for path in data:
            self.import_csv(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if _dropped_files(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt naming
        paths = _dropped_files(event)
        if paths:
            event.acceptProposedAction()
            self.open_dropped(paths)

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
        views = (
            self.preview,
            self.outline,
            self.problems,
            self.properties,
            self.code,
            self.chat,
        )
        for view in views:
            view.set_document(document)
        self._connect(document)
        self.show_workspace()

    def show_error(self, title: str, error: Exception) -> None:
        QMessageBox.warning(self, title, str(error))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        if not self.confirm_discard():
            event.ignore()
            return
        if self.tool_server.listening:
            self.tool_server.stop()
        self.chat.wait()  # let a running request finish before its thread goes
        event.accept()

    def _connect(self, document: Document) -> None:
        document.state_changed.connect(self._update_state)
        document.selection_changed.connect(self._update_state)
        document.changed.connect(self._show_problems)
        self._update_state()
        self._show_problems()

    def _show_problems(self) -> None:
        wanted = self.problems.count() > 0 and not self.on_start_page
        self.problems_dock.setVisible(wanted)

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
        path = self.document.path
        self._project_name.setText(path.stem if path is not None else "Untitled")
        if not history.is_clean:
            self._save_state.setText("Unsaved changes")
        else:
            self._save_state.setText("Saved" if path is not None else "Not saved yet")

    def _save_to(self, path: Path | None) -> bool:
        try:
            self.document.save(path)
        except OSError as exc:
            self.show_error("Cannot save the project", exc)
            return False
        self._add_recent(self.document.path)
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
        # Panels, not floating tool windows: no title bar, nothing to undock.
        dock.setTitleBarWidget(QWidget())
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(area, dock)
        return dock

    def _build_menus(self) -> None:
        file = self.menuBar().addMenu("&File")
        self.home_action = self._action(file, "Start &Page", self.show_start)
        file.addSeparator()
        self._action(file, "&New", self.new_project, QKeySequence.StandardKey.New)
        self._action(file, "&Open…", self._open_dialog, QKeySequence.StandardKey.Open)
        self._action(file, "&Save", self.save, QKeySequence.StandardKey.Save)
        self._action(file, "Save &As…", self.save_as, QKeySequence.StandardKey.SaveAs)
        file.addSeparator()
        self.export_action = self._action(
            file, "&Export Figure…", self._export_dialog, "Ctrl+E"
        )
        self.script_action = self._action(
            file, "Export &Python Script…", self._script_dialog, "Ctrl+Shift+E"
        )
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
        self.import_action = self._action(
            insert, "&Import Data…", lambda: self.import_csv(), "Ctrl+I"
        )
        self.plot_action = self._action(
            insert, "Add &Plot…", self.add_plot, "Ctrl+Shift+P"
        )
        self.fit_action = self._action(
            insert, "Add &Fit…", self.add_fit, "Ctrl+Shift+F"
        )
        self.note_action = self._action(insert, "Add &Note…", lambda: self.add_note())
        self.panel_menu = insert.addMenu("Add Pa&nel")
        self.panel_actions = {}
        for side, text in PANEL_SIDES:
            action = self.panel_menu.addAction(text.replace("Add ", "").capitalize())
            action.triggered.connect(lambda _=False, s=side: self.add_panel(s))
            self.panel_actions[side] = action

        view = self.menuBar().addMenu("&View")
        self.code_action = self._toggle(view, "&Python Code", self.show_code)
        self.code_action.setShortcut(QKeySequence("Ctrl+Shift+Y"))
        self.addAction(self.code_action)

        assistant = self.menuBar().addMenu("&Assistant")
        self.chat_action = self._toggle(assistant, "&Chat", self.show_chat)
        self.chat_action.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.addAction(self.chat_action)
        assistant.addSeparator()
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

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
        bar.setObjectName("main")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        bar.toggleViewAction().setVisible(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self.toolbar = bar

        self.home_action.setIcon(theme.icon("fit", theme.ACCENT, 18))
        self.home_action.setToolTip("Start page")
        bar.addAction(self.home_action)
        home = bar.widgetForAction(self.home_action)
        home.setObjectName("quiet")
        home.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        self._project_name = QLabel()
        self._project_name.setObjectName("projectName")
        self._save_state = QLabel()
        self._save_state.setObjectName("saveState")
        bar.addWidget(self._project_name)
        bar.addWidget(self._save_state)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        for action, text in ((self.import_action, "Data"), (self.plot_action, "Plot")):
            action.setIcon(theme.icon("plus"))
            action.setIconText(text)
            bar.addAction(action)
        self.fit_action.setIcon(theme.icon("fit"))
        self.fit_action.setIconText("Fit")
        bar.addAction(self.fit_action)
        panel = QToolButton()
        panel.setText("Panel")
        panel.setIcon(theme.icon("plus"))
        panel.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        panel.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        panel.setMenu(self.panel_menu)
        panel.setToolTip("Add a panel beside or inside the selected one")
        bar.addWidget(panel)
        bar.addSeparator()
        for action, name in ((self.undo_action, "undo"), (self.redo_action, "redo")):
            action.setIcon(theme.icon(name))
            bar.addAction(action)
            button = bar.widgetForAction(action)
            button.setObjectName("quiet")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.chat_action.setIcon(theme.icon("chat"))
        self.chat_action.setIconText("Assistant")
        bar.addAction(self.chat_action)
        self.code_action.setIcon(theme.icon("code"))
        self.code_action.setIconText("Python code")
        bar.addAction(self.code_action)
        bar.addSeparator()
        self.export_action.setIconText("Export…")
        bar.addAction(self.export_action)
        export_button: QToolButton = bar.widgetForAction(self.export_action)
        export_button.setObjectName("primary")
        export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

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


def _documents() -> Path:
    location = QStandardPaths.StandardLocation.DocumentsLocation
    folder = QStandardPaths.writableLocation(location)
    return Path(folder) if folder else Path.home()


def _side_panel(widget: QWidget) -> QWidget:
    panel = QWidget()
    panel.setObjectName("sidePanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(8, 10, 8, 8)
    layout.addWidget(widget)
    return panel


def _dropped_files(event) -> list[Path]:
    mime = event.mimeData()
    if not mime.hasUrls():
        return []
    return [Path(url.toLocalFile()) for url in mime.urls() if url.isLocalFile()]
