"""The main window: outline, preview and problems around one Document."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QSettings,
    QSize,
    QStandardPaths,
    Qt,
    QUrl,
)
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

from figscribe.allan import allan_axes
from figscribe.assistant.chat import Provider
from figscribe.assistant.toolserver import ToolServer
from figscribe.codegen import file_stems, generate, script_name
from figscribe.commands import (
    CommandError,
    InsertItem,
    Macro,
    SetField,
    add_figure,
    add_panel,
    duplicate_artists,
    duplicate_axes,
    duplicate_figure,
    find,
    paste_style,
    remove_artist,
    remove_artists,
    remove_axes,
    remove_figure,
    remove_source,
    same_range,
)
from figscribe.commands.core import noun, walk
from figscribe.examples import bundled_example
from figscribe.fit import FitError, add_fit, set_left_out, update_fit
from figscribe.gui import clipboard, markings, reveal, theme
from figscribe.gui.chatpanel import ChatPanel
from figscribe.gui.codepanel import CodePanel
from figscribe.gui.databar import DataBar
from figscribe.gui.document import Document, axis_id, split_axis
from figscribe.gui.errors import explain
from figscribe.gui.figures import FigureTabs, move_figure
from figscribe.gui.fitdialog import FitDialog
from figscribe.gui.importdialog import ImportDialog
from figscribe.gui.names import artist_name, panel_name
from figscribe.gui.outline import PANEL_SIDES, Outline
from figscribe.gui.palette import CommandPalette, Entry, menu_entries
from figscribe.gui.plotdialog import NEW_PANEL, PlotDialog
from figscribe.gui.preview import Preview
from figscribe.gui.problems import Problems
from figscribe.gui.properties import PropertyPanel
from figscribe.gui.start import DOCS_URL, StartPage
from figscribe.io import DataError, numpy_source
from figscribe.io.files import resolve_path
from figscribe.io.numpyfile import array_names, read_numpy
from figscribe.model import (
    AllanDeviationPlot,
    Annotation,
    ArrayRef,
    ArtistBase,
    Axes,
    AxisSpec,
    Colorbar,
    ColumnRef,
    Figure,
    FitCurve,
    Histogram,
    ImagePlot,
    ResidualPlot,
)
from figscribe.model.validate import FITTABLE
from figscribe.render import export, export_bytes
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
DATA_FILTER = (
    "Data (*.csv *.tsv *.txt *.dat *.npy *.npz);;Delimited text (*.csv *.tsv "
    "*.txt *.dat);;NumPy (*.npy *.npz);;All files (*)"
)
EXPORT_FILTER = "PDF (*.pdf);;SVG (*.svg);;PNG (*.png)"
SCRIPT_FILTER = "Python script (*.py)"
EXPORT_ALL_FORMATS = {
    "PDF": ".pdf",
    "SVG": ".svg",
    "PNG": ".png",
    "Python scripts": ".py",
}
"""What Export All Figures writes, each figure into a file of its own."""
DATA_SUFFIXES = {".csv", ".tsv", ".txt", ".dat", ".npy", ".npz"}
NUMPY_SUFFIXES = {".npy", ".npz"}
START_FILTER = (
    "Data or project (*.csv *.tsv *.txt *.dat *.npy *.npz *.figscribe);;All files (*)"
)
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
        self.ask_name: Callable[[str, str, str], str | None] = self._ask_name
        """Asks for a name, given the current one; None if cancelled."""
        self._copied_style: ArtistBase | None = None
        """A copy of the plot whose style Copy Style took; pasted by Paste Style."""
        """Runs a dialog, True if accepted; replaced in tests."""

        self.preview = Preview(self.document)
        self.start = StartPage()
        self._connect_start(self.start)
        self.chat = ChatPanel(self.document, provider=self._provider())
        self.chat.provider_changed.connect(self._remember_provider)
        self.chat.hide()
        self.chat.busy_changed.connect(
            lambda busy: self.statusBar().showMessage(
                "Assistant at work…" if busy else ""
            )
        )
        self.code = CodePanel(self.document)
        self.code.save_requested.connect(self._script_dialog)
        self.code.hide()
        self.data_bar = DataBar(self.document)
        self.figure_tabs = FigureTabs(self.document)
        self.figure_tabs.requested.connect(self.figure_action)
        self.figure_tabs.add_requested.connect(self.add_figure)
        figure_area = QWidget()
        column = QVBoxLayout(figure_area)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.figure_tabs)
        column.addWidget(self.data_bar)
        column.addWidget(self.preview, 1)
        self.workspace = QSplitter(Qt.Orientation.Vertical)
        self.workspace.setChildrenCollapsible(False)
        self.workspace.addWidget(figure_area)
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
        self.properties.axis_range = self.preview.axis_limits
        self.properties.drawn_color = self.preview.drawn_color
        self.outline.add_requested.connect(self._add_plot_to)
        self.outline.import_requested.connect(lambda: self.import_csv())
        self.outline.panel_requested.connect(
            lambda oid, side: self.add_panel(side, oid)
        )
        self.outline.delete_requested.connect(self._delete)
        self.outline.figure_requested.connect(self.figure_action)
        self.outline.note_requested.connect(self.add_note)
        self.outline.marking_requested.connect(
            lambda oid, kind, orientation: self.add_marking(kind, orientation, oid)
        )
        self.outline.same_range_requested.connect(self.same_range)
        self.outline.reveal_requested.connect(self.reveal_source)
        self.contents_dock = self._dock(
            "Contents", _side_panel(self.outline), Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.properties_dock = self._dock(
            "Properties",
            _with_search(self.properties),
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        self.properties.edit_fit = self.edit_fit
        self.preview.show_error = self.show_error
        self.preview.fit_requested.connect(self._fit_plot)
        self.preview.same_range_requested.connect(self.same_range)
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

    def _provider(self) -> Provider:
        """The assistant's model from the settings; API keys are never stored."""
        if self.settings is None or not self.settings.value("assistant/kind"):
            return Provider()
        value = self.settings.value
        return Provider(
            kind=value("assistant/kind"),
            model=value("assistant/model", "", type=str),
            base_url=value("assistant/base_url", "", type=str) or None,
            vision=value("assistant/vision", True, type=bool),
        )

    def _remember_provider(self, provider: Provider) -> None:
        if self.settings is None:
            return
        self.settings.setValue("assistant/kind", provider.kind)
        self.settings.setValue("assistant/model", provider.model)
        self.settings.setValue("assistant/base_url", provider.base_url or "")
        self.settings.setValue("assistant/vision", provider.vision)

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

    def export_script(self, path: str | Path, figure=None) -> None:
        """Write the Python script that draws `figure` (default: the shown
        one) to `path`."""
        figure = figure or self.document.figure
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

    def export_all(self, folder: str | Path, suffix: str) -> list[Path]:
        """Write every figure into `folder`, each named after it, as `suffix`
        (".pdf", ".svg", ".png", or ".py" for its script); the paths written."""
        folder = Path(folder)
        written: list[Path] = []
        for figure, path in zip(
            self.document.project.figures,
            export_names(self.document.project.figures, folder, suffix),
            strict=True,
        ):
            try:
                if suffix == ".py":
                    self.export_script(path, figure)
                else:
                    export(figure, self.document.data, path)
            except Exception as exc:
                self.show_error(f"Cannot export {figure.name}", exc)
                break
            written.append(path)
        return written

    def _export_all_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Export all figures into", str(self.document.project_dir or "")
        )
        if not folder:
            return
        formats = list(EXPORT_ALL_FORMATS)
        chosen, ok = QInputDialog.getItem(
            self, "Export all figures", "Each figure as:", formats, 0, False
        )
        if not ok:
            return
        suffix = EXPORT_ALL_FORMATS[chosen]
        names = export_names(self.document.project.figures, Path(folder), suffix)
        there = [p.name for p in names if p.exists()]
        if there and not self.ask(
            "Replace files",
            f"{folder} already has {', '.join(there)}. Replace them?",
        ):
            return
        written = self.export_all(folder, suffix)
        self.statusBar().showMessage(f"Exported {len(written)} figures", 5000)

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
        if Path(path).suffix.lower() in NUMPY_SUFFIXES:
            return self.import_numpy(path)
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
        axes = _axes_with_id(figure, self._target_axes(figure))
        steps += self._plot_steps(figure, artist, axes, dialog.unit_of)
        self._push(Macro(f"Add {Path(source.path).name} and plot", steps))
        self.document.select(artist.id)
        return True

    def import_numpy(self, path: str | Path) -> bool:
        """Add a .npy or .npz file; a 2-D array is shown as an image at once,
        with a colour bar, in the same undo step."""
        path = Path(path)
        base = self.document.project_dir or path.parent
        try:
            raw = path.read_bytes()
            chosen = None
            if path.suffix.lower() == ".npz":
                names = array_names(raw, path.name)
                chosen = next((n for n in names if _ndim(raw, n) == 2), names[0])
            source = numpy_source(path, base, array=chosen)
            if self.document.project_dir is None:
                source = source.model_copy(update={"path": str(path.resolve())})
            values = read_numpy(source, raw, path.name)
        except (OSError, DataError) as exc:
            self.show_error(f"Cannot read {path.name}", exc)
            return False
        steps = [InsertItem(None, "sources", source)]
        figure = self.document.figure
        if values.ndim != 2 or figure is None:
            self._push(Macro(f"Add {path.name}", steps))
            self.document.select(source.id)
            return True
        image = ImagePlot(data=ArrayRef(source=source.id), colorbar=Colorbar())
        axes_id = self._target_axes(figure)
        if axes_id is None:
            steps.append(InsertItem(figure.id, "axes", Axes(artists=[image])))
        else:
            steps.append(InsertItem(axes_id, "artists", image))
        self._push(Macro(f"Add {path.name} as an image", steps))
        self.document.select(image.id)
        return True

    def _plot_steps(self, figure, artist, axes: Axes | None, unit_of=None) -> list:
        """Put `artist` into `axes`, or into a new panel if None; while the
        panel is empty, name its axes after the plotted columns and units."""
        unit_of = unit_of or (lambda column: None)
        if isinstance(artist, AllanDeviationPlot):
            labels = allan_axes()
        elif isinstance(artist, Histogram):
            values = artist.values
            labels = {
                "x": AxisSpec(label=str(values.column), unit=unit_of(values.column)),
                "y": AxisSpec(label="Count"),
            }
        elif isinstance(getattr(artist, "x", None), ColumnRef):
            labels = {
                name: AxisSpec(label=str(ref.column), unit=unit_of(ref.column))
                for name, ref in (("x", artist.x), ("y", artist.y))
            }
        else:
            labels = {}  # an image: its colour bar says what it shows
        if axes is None:
            return [InsertItem(figure.id, "axes", Axes(artists=[artist], **labels))]
        steps = [
            SetField(axes.id, (name,), spec)
            for name, spec in labels.items()
            if getattr(axes, name).label is None and not axes.artists
        ]
        return [*steps, InsertItem(axes.id, "artists", artist)]

    def add_plot(self) -> None:
        """Add a plot of the data's columns, to the panel chosen in the dialog."""
        columns = self.document.column_choices()
        arrays = self.document.array_choices()
        figure = self.document.figure
        if not (columns or arrays) or figure is None:
            self.show_error("Nothing to plot", "Import a data file first.")
            return
        target = self._target_axes(figure)
        targets = [(panel_name(figure, axes), axes.id) for axes in figure.axes]
        if figure.axes:
            targets.append(("A new panel to the right", NEW_PANEL))
        dialog = PlotDialog(
            columns,
            self,
            arrays=arrays,
            targets=targets,
            target=target,
            data=self.document.data,
            summary=self._data_summary(columns),
        )
        if not self.run_dialog(dialog):
            return
        artist = dialog.artist()
        steps = []
        if dialog.target_id() == NEW_PANEL:
            beside = _axes_with_id(figure, target)
            if beside.inset is not None:
                beside = _axes_with_id(figure, beside.inset.parent)
            command, axes = add_panel(self.document.project, beside.id, "right")
            steps.append(command)
        else:
            axes = _axes_with_id(figure, dialog.target_id())
        steps += self._plot_steps(figure, artist, axes)
        self._push(Macro(f"Add {noun(artist)}", steps))
        self.document.select(artist.id)

    def _data_summary(self, columns) -> str:
        """ "scan.csv · 41 rows", or how many files there are."""
        sources = self.document.project.sources
        if len(sources) != 1:
            return f"{len(sources)} data files"
        source = sources[0]
        name = Path(source.path).name
        rows = getattr(source, "row_count", None)
        if rows is None and columns:
            try:
                rows = len(self.document.data(columns[0][1]))
            except Exception:  # noqa: BLE001 - the summary is only a courtesy
                return name
        return name if rows is None else f"{name} · {rows} rows"

    def _target_axes(self, figure) -> str | None:
        """The selected axes, the axes of the selected plot, or the first one."""
        selected = self.document.selected
        axis = split_axis(selected)
        if axis is not None:
            selected = axis[0]  # an axis stands for its panel
        for axes in figure.axes:
            if axes.id == selected or any(a.id == selected for a in axes.artists):
                return axes.id
        return figure.axes[0].id if figure.axes else None

    def add_fit(self) -> None:
        """Fit a model to the selected plot (or the only one) and add it."""
        target = self._fit_target()
        if target is None:
            self.show_error("Nothing to fit", "Select the plot to fit, then try again.")
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
            command = self._with_outliers(command, dialog)
        except FitError as exc:
            self.show_error("Cannot fit", exc)
            return
        self._push(command)
        self.document.select(fit.id)

    def _fit_plot(self, oid: str) -> None:
        self.document.select(oid)
        self.add_fit()

    def edit_fit(self, fit_id: str) -> None:
        """Open the fit dialog on the fit `fit_id` and take what it changes,
        as one undo step."""
        try:
            fit = find(self.document.project, fit_id)
            target = find(self.document.project, fit.target)
            dialog = FitDialog(target, self.document.data, parent=self, fit=fit)
        except Exception as exc:  # gone, or the data cannot be read
            self.show_error("Cannot change the fit", exc)
            return
        if not self.run_dialog(dialog) or dialog.fit() is None:
            return
        try:
            command = update_fit(self.document.project, fit_id, dialog.fit())
            command = self._with_outliers(command, dialog)
        except FitError as exc:
            self.show_error("Cannot change the fit", exc)
            return
        self._push(command)

    def _with_outliers(self, command: Macro, dialog: FitDialog) -> Macro:
        """`command`, and the outliers the user confirmed in the dialog left
        out of the plot, with the plot's fits fitted again: one step."""
        rows = dialog.left_out_rows()
        if rows is None:
            return command
        staging = self.document.project.model_copy(deep=True)
        command.apply(staging)
        plot_id = dialog.target.id
        leave = set_left_out(staging, plot_id, rows, self.document.data)
        note = SetField(plot_id, ("left_out_note",), dialog.left_out_note())
        count = len(dialog.pending)
        return Macro(
            f"{command.description} and leave out {count} outlier"
            + ("s" * (count != 1)),
            [*command.steps, *leave.steps, note],
        )

    def add_note(self, oid: str | None = None) -> None:
        """Add a note in the middle of a panel; drag it in the preview."""
        figure = self.document.figure
        if figure is None:
            return
        target = oid if oid is not None else self._target_axes(figure)
        if target is None:
            self.show_error("No panel", "Add a panel or a plot first.")
            return
        text = self.ask_text(
            "Add note",
            "Text, over several lines if you like (LaTeX allowed, e.g. $\\mu$):",
        )
        if not text:
            return
        note = Annotation(text=text, position=(0.5, 0.5), coords="axes")
        self._push(InsertItem(target, "artists", note))
        self.document.select(note.id)

    def add_marking(self, kind: str, orientation: str, oid: str | None = None) -> None:
        """Add a reference line or a shaded range in the middle of what a
        panel shows; its value is then typed in the property panel, or it is
        placed by right-clicking the preview."""
        figure = self.document.figure
        if figure is None:
            return
        target = oid if oid is not None else self._target_axes(figure)
        axes = next((a for a in figure.axes if a.id == target), None)
        if axes is None:
            self.show_error("No panel", "Add a panel or a plot first.")
            return
        field = "x" if orientation == "vertical" else "y"
        spec = getattr(axes, field)
        shown = self.preview.axis_limits(axis_id(axes.id, field))
        low, high = sorted(shown or spec.limits or (0.0, 1.0))
        log = spec.scale == "log" and low > 0
        made = markings.marking(kind, orientation, low, high, log=log)
        self._push(markings.add(axes.id, made))
        self.document.select(made.id)

    def _ask_text(self, title: str, prompt: str) -> str | None:
        """Several lines of text; None if cancelled."""
        text, ok = QInputDialog.getMultiLineText(self, title, prompt)
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

    def add_figure(self) -> None:
        """Add a figure after the shown one, with its look, and show it."""
        shown = self.document.figure
        after = shown.id if shown is not None else None
        command, figure = add_figure(self.document.project, after)
        self._push(command)
        self.document.select(figure.id)

    def duplicate_figure(self, oid: str | None = None) -> None:
        """Copy the figure `oid` (default: the shown one) and show the copy."""
        oid = oid or (self.document.figure.id if self.document.figure else None)
        if oid is None:
            return
        command, copy = duplicate_figure(self.document.project, oid)
        self._push(command)
        self.document.select(copy.id)

    def rename_figure(self, oid: str | None = None) -> None:
        figure = self._figure(oid)
        if figure is None:
            return
        name = self.ask_name("Rename figure", "Name of the figure:", figure.name)
        if name and name != figure.name:
            self._push(SetField(figure.id, ("name",), name, "Rename figure"))

    def figure_action(self, oid: str, what: str) -> None:
        """Do `what` with the figure `oid`, as the figure menu offers it."""
        if what == "rename":
            self.rename_figure(oid)
        elif what == "duplicate":
            self.duplicate_figure(oid)
        elif what in ("earlier", "later"):
            try:
                move_figure(self.document, oid, -1 if what == "earlier" else 1)
            except CommandError as exc:
                self.show_error("Cannot move the figure", exc)
        elif what == "delete":
            self._delete(oid)

    def _figure(self, oid: str | None):
        if oid is None:
            return self.document.figure
        return next((f for f in self.document.project.figures if f.id == oid), None)

    def _ask_name(self, title: str, prompt: str, current: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, prompt, text=current)
        return text.strip() or None if ok else None

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

    def find_setting(self) -> None:
        """Put the cursor in the search above the property panel."""
        self.properties.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.properties.search.selectAll()

    def open_palette(self) -> None:
        """Find any menu action or setting of the selection by typing."""
        entries = [
            entry
            for entry in menu_entries(self.menuBar())
            if entry.run != self.palette_action.trigger
        ]
        entries += [
            Entry(
                caption,
                f"Setting · {title}",
                lambda c=caption, t=title: self._reveal_setting(c, t),
            )
            for caption, title, _ in self.properties.settings()
        ]
        palette = CommandPalette(entries, self)
        if self.run_dialog(palette) and palette.chosen is not None:
            palette.chosen.run()

    def _reveal_setting(self, caption: str, title: str) -> None:
        self.properties_dock.show()
        self.properties.reveal(caption, title)

    def show_chat(self, on: bool) -> None:
        """Show or hide the built-in assistant under the preview."""
        self.chat.setVisible(on)
        if on:
            self.chat.input.setFocus()

    def _choose_model(self) -> None:
        self.chat_action.setChecked(True)
        self.chat.choose_model()

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
        """Remove the selected object, with what depends on it; several
        plots chosen together go at once."""
        several = self.document.selection
        if len(several) > 1:
            self._push(remove_artists(self.document.project, several))
            return
        oid = self.document.selected
        for obj, _, field in walk(self.document.project):
            if obj.id != oid:
                continue
            if isinstance(obj, ArtistBase) and field == "artists":
                self._push(remove_artist(self.document.project, oid))
            elif isinstance(obj, Axes):
                self._push(remove_axes(self.document.project, oid))
            elif field == "figures":
                try:
                    self._push(remove_figure(self.document.project, oid))
                except CommandError as exc:
                    self.show_error("Cannot delete the figure", exc)
            elif field == "sources":
                self._remove_source(oid)
            return

    def _remove_source(self, oid: str) -> None:
        """Remove a data file; first ask, naming them, if plots draw from it."""
        project = self.document.project
        command = remove_source(project, oid)
        going = [
            artist_name(find(project, step.item_id))
            for step in reversed(command.steps)
            if step.field == "artists"
        ]
        name = Path(find(project, oid).path).name
        if going and not self.ask(
            "Remove data file",
            f"{name} is used by: {', '.join(going)}.\n\nRemove it together with "
            "them? The file itself stays on disk; Undo brings everything back.",
        ):
            return
        self._push(command)

    def _push(self, command) -> None:
        try:
            self.document.push(command)
        except CommandError as exc:
            self.show_error("The change was refused", exc)

    def _chosen(self) -> list:
        """The objects selected, leaving out an axis, which stands for no object
        of its own."""
        project = self.document.project
        chosen = []
        for oid in self.document.selection:
            if split_axis(oid) is not None:
                return []
            try:
                chosen.append(find(project, oid))
            except CommandError:
                return []
        return chosen

    def duplicate_selected(self) -> None:
        """Copy what is selected and select the copy: a figure, a panel with its
        plots (beside it), or plots (right after the originals)."""
        chosen = self._chosen()
        if not _can_duplicate(chosen):
            return
        project = self.document.project
        if isinstance(chosen[0], Figure):
            self.duplicate_figure(chosen[0].id)
            return
        try:
            if isinstance(chosen[0], Axes):
                command, copy = duplicate_axes(project, chosen[0].id)
                made = [copy]
            else:
                command, made = duplicate_artists(project, [o.id for o in chosen])
            self.document.push(command)
        except CommandError as exc:
            self.show_error("Cannot duplicate", exc)
            return
        self.document.select_many([each.id for each in made])

    def copy_style(self) -> None:
        """Take the look of the selected plot, for Paste Style."""
        chosen = self._chosen()
        if not chosen or not isinstance(chosen[-1], ArtistBase):
            return
        self._copied_style = chosen[-1].model_copy(deep=True)
        self._update_state()
        self.statusBar().showMessage(
            f"Copied the style of {artist_name(chosen[-1])}", 4000
        )

    def paste_style(self) -> None:
        """Give the selected plots the look Copy Style took, as one step."""
        plots = [o.id for o in self._chosen() if isinstance(o, ArtistBase)]
        if self._copied_style is None or not plots:
            return
        command = paste_style(self.document.project, plots, self._copied_style)
        if not command.steps:
            self.statusBar().showMessage(
                "Nothing to change: the plot already has this style", 4000
            )
            return
        self._push(command)

    def same_range(self, axes_id: str, field: str) -> None:
        """Give every panel of the figure the range that the panel `axes_id`
        shows on its x or y axis, as one step."""
        project = self.document.project
        shown = self.preview.axis_range(axis_id(axes_id, field))
        if shown is None:
            self.show_error("Cannot read the range", "The panel is not drawn.")
            return
        try:
            command, skipped = same_range(project, axes_id, field, shown)
        except CommandError as exc:
            self.show_error("Cannot give the panels one range", exc)
            return
        if command.steps:
            # A panel zoomed in the preview shows the new range, not the zoom.
            self.preview.drop_view([step.target for step in command.steps])
            self._push(command)
            message = f"All panels show the {field} range now."
        else:
            message = f"All panels show this {field} range already."
        if skipped:
            figure = self.document.figure
            names = ", ".join(panel_name(figure, each) for each in skipped)
            message += f" Left out, as their axis has another scale or unit: {names}."
        self.statusBar().showMessage(message, 8000)

    def copy_figure(self) -> None:
        """Put the shown figure on the clipboard as PNG and SVG, exactly as
        exporting would write them, for slides and documents."""
        figure = self.document.figure
        if figure is None:
            return
        try:
            png = export_bytes(figure, self.document.data, ".png")
            svg = export_bytes(figure, self.document.data, ".svg")
        except Exception as exc:
            self.show_error("Cannot copy the figure", exc)
            return
        clipboard.put_figure(png, svg)
        self.statusBar().showMessage("Copied the figure to the clipboard", 5000)

    def reveal_source(self, oid: str) -> None:
        """Show the data file in the system's file manager."""
        source = find(self.document.project, oid)
        path = resolve_path(source.path, self.document.base_dir)
        if not path.exists():
            self.show_error(
                "Cannot show the file",
                f"{path.name} is not at {path}. Use “Locate file…” in the bar "
                "above the figure to find it again.",
            )
            return
        reveal.show_in_file_manager(path)

    # --- window -------------------------------------------------------------

    def set_document(self, document: Document) -> None:
        document.allow_preview = self.document.allow_preview
        self.document = document
        views = (
            self.figure_tabs,
            self.data_bar,
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

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt naming
        super().changeEvent(event)
        # A data file may have been changed in another program meanwhile.
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self.data_bar.rebuild()

    def show_error(self, title: str, error: Exception | str) -> None:
        """Tell what went wrong: a message, or an error explained in plain words."""
        text = error if isinstance(error, str) else explain(error)
        QMessageBox.warning(self, title, text)

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
        selected = self.document.selected
        self.delete_action.setEnabled(
            selected is not None and split_axis(selected) is None
        )
        chosen = self._chosen()
        self.duplicate_action.setEnabled(_can_duplicate(chosen))
        self.copy_style_action.setEnabled(
            bool(chosen) and isinstance(chosen[-1], ArtistBase)
        )
        self.paste_style_action.setEnabled(
            self._copied_style is not None
            and any(isinstance(obj, ArtistBase) for obj in chosen)
        )
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
        self._action(file, "Export A&ll Figures…", self._export_all_dialog)
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
        self.duplicate_action = self._action(
            edit, "Du&plicate", self.duplicate_selected, "Ctrl+D"
        )
        edit.addSeparator()
        self.copy_style_action = self._action(
            edit, "Copy &Style", self.copy_style, "Ctrl+Alt+C"
        )
        self.paste_style_action = self._action(
            edit, "Paste St&yle", self.paste_style, "Ctrl+Alt+V"
        )
        self.copy_figure_action = self._action(
            edit, "&Copy Figure", self.copy_figure, "Ctrl+Shift+C"
        )
        edit.addSeparator()
        self._action(edit, "&Find Setting", self.find_setting, "Ctrl+F")
        self.palette_action = self._action(
            edit, "Find Setting or &Action…", self.open_palette, "Ctrl+K"
        )

        insert = self.menuBar().addMenu("&Insert")
        self.import_action = self._action(
            insert, "&Import Data…", lambda: self.import_csv(), "Ctrl+I"
        )
        self.add_figure_action = self._action(insert, "Add Fi&gure", self.add_figure)
        self._action(insert, "D&uplicate Figure", lambda: self.duplicate_figure())
        insert.addSeparator()
        self.plot_action = self._action(
            insert, "Add &Plot…", self.add_plot, "Ctrl+Shift+P"
        )
        self.fit_action = self._action(
            insert, "Add &Fit…", self.add_fit, "Ctrl+Shift+F"
        )
        self.note_action = self._action(insert, "Add &Note…", lambda: self.add_note())
        self.marking_menu = insert.addMenu("Add &Line or Range")
        for text, kind, orientation in markings.ENTRIES:
            action = self.marking_menu.addAction(text)
            action.triggered.connect(
                lambda _=False, k=kind, o=orientation: self.add_marking(k, o)
            )
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
        self._action(assistant, "Choose &Model…", lambda: self._choose_model())
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

        # What can be added, in the order a figure is built: data, then what
        # holds what.
        self.import_action.setIcon(theme.icon("plus"))
        self.import_action.setIconText("Data")
        bar.addAction(self.import_action)
        self.add_figure_action.setIcon(theme.icon("plus"))
        self.add_figure_action.setIconText("Figure")
        self.add_figure_action.setToolTip("Add a figure after the shown one")
        bar.addAction(self.add_figure_action)
        panel = QToolButton()
        panel.setText("Panel")
        panel.setIcon(theme.icon("plus"))
        panel.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        panel.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        panel.setMenu(self.panel_menu)
        panel.setToolTip("Add a panel beside or inside the selected one")
        bar.addWidget(panel)
        self.plot_action.setIcon(theme.icon("plus"))
        self.plot_action.setIconText("Plot")
        bar.addAction(self.plot_action)
        self.fit_action.setIcon(theme.icon("fit"))
        self.fit_action.setIconText("Fit")
        bar.addAction(self.fit_action)
        self.note_action.setIcon(theme.icon("plus"))
        self.note_action.setIconText("Note")
        bar.addAction(self.note_action)
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


def _can_duplicate(chosen: list) -> bool:
    """Whether Duplicate applies to the selected objects: a figure or a panel
    of the grid alone, or plots (not residuals, which come with a fit)."""
    if not chosen:
        return False
    if len(chosen) == 1 and isinstance(chosen[0], Figure):
        return True
    if len(chosen) == 1 and isinstance(chosen[0], Axes):
        return chosen[0].inset is None
    return all(
        isinstance(obj, ArtistBase) and not isinstance(obj, ResidualPlot)
        for obj in chosen
    )


def _ndim(raw: bytes, name: str) -> int:
    """Dimensions of the array `name` in an .npz file's bytes."""
    import io

    import numpy as np

    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        return archive[name].ndim


def _documents() -> Path:
    location = QStandardPaths.StandardLocation.DocumentsLocation
    folder = QStandardPaths.writableLocation(location)
    return Path(folder) if folder else Path.home()


def _with_search(panel: PropertyPanel) -> QWidget:
    """The property panel under its search field, which stays in place while
    the form scrolls."""
    holder = QWidget()
    holder.setObjectName("sidePanel")
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(0)
    row = QVBoxLayout()
    row.setContentsMargins(12, 10, 12, 6)
    row.addWidget(panel.search)
    column.addLayout(row)
    column.addWidget(panel, 1)
    return holder


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


def export_names(figures, folder: Path, suffix: str) -> list[Path]:
    """A file in `folder` for each figure, named after it; a name two figures
    share gets a number."""
    return [folder / f"{stem}{suffix}" for stem in file_stems(figures)]


def _axes_with_id(figure, oid: str | None) -> Axes | None:
    return next((axes for axes in figure.axes if axes.id == oid), None)
