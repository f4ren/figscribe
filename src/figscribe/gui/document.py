"""The open project as the GUI sees it: model, file, history, data, selection.

Every change to the model goes through `push`, `undo` or `redo`, and every
one of them emits `changed`. Views never mutate the model themselves; they
build a command and push it, then redraw when `changed` arrives.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from figscribe import __version__
from figscribe.commands import Command, CommandError, History, find
from figscribe.io import load_data
from figscribe.io.files import resolve_path
from figscribe.io.refresh import source_state
from figscribe.model import ArrayRef, ColumnRef, Figure, Project, dumps, loads
from figscribe.render import DataProvider
from figscribe.tools.workspace import array_choices, column_choices

AXIS_FIELDS = ("x", "y", "y_right")
"""The axes of a panel that can be selected on their own."""


def axis_id(axes_id: str, field: str) -> str:
    """The selection id of one axis of a panel, e.g. "3f2a…/x"."""
    return f"{axes_id}/{field}"


def split_axis(oid: str | None) -> tuple[str, str] | None:
    """(panel id, "x" | "y" | "y_right") for an axis's selection id."""
    if oid is None or "/" not in oid:
        return None
    axes_id, field = oid.rsplit("/", 1)
    return (axes_id, field) if field in AXIS_FIELDS else None


class Document(QObject):
    changed = Signal()
    """The model changed: through a command, undo, redo, or a new file."""
    selection_changed = Signal(object)
    """The selected object id, or None."""
    state_changed = Signal()
    """Path or saved state changed; the window title follows it."""
    figure_changed = Signal()
    """Another figure is shown, since something in it was selected; a change
    of the model announces itself through `changed` instead."""

    def __init__(self, project: Project | None = None, path: Path | None = None):
        super().__init__()
        self._set(project or _new_project(), path)

    # --- file ---------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path) -> Document:
        path = Path(path)
        return cls(loads(path.read_text(encoding="utf-8")), path)

    def save(self, path: str | Path | None = None) -> None:
        """Write the project; with a new `path`, it becomes the document's file."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("the project has no file yet; give a path")
        target.write_text(dumps(self.project), encoding="utf-8")
        self.path = target
        self.history.mark_clean()
        self.state_changed.emit()

    @property
    def base_dir(self) -> Path:
        """Where the project's relative data paths start: next to its file."""
        return self.path.parent if self.path is not None else Path(os.getcwd())

    @property
    def project_dir(self) -> Path | None:
        """The project file's directory; None until the project is saved."""
        return self.path.parent if self.path is not None else None

    @property
    def title(self) -> str:
        name = self.path.name if self.path is not None else "Untitled"
        return f"{name}{'' if self.history.is_clean else '*'} — figscribe"

    # --- changes ------------------------------------------------------------

    def push(self, command: Command) -> None:
        """Apply `command` as one undo step. Raises CommandError, changing nothing."""
        self.history.push(command)
        self._after_change()

    def undo(self) -> None:
        self.history.undo()
        self._after_change()

    def redo(self) -> None:
        self.history.redo()
        self._after_change()

    # --- data ---------------------------------------------------------------

    @property
    def data(self) -> DataProvider:
        """Reads the project's sources, rebuilt whenever they change."""
        if self._data is None or self._data_sources != self.project.sources:
            self._data = load_data(self.project, self.base_dir)
            self._data_sources = [s.model_copy(deep=True) for s in self.project.sources]
        return self._data

    def data_states(self) -> dict[str, str]:
        """ "changed" or "missing" for each source whose file is not as imported.

        A file is hashed again only when its size or time stamp changed, so
        asking after every edit costs a look at each file, not reading it.
        """
        states = {}
        for source in self.project.sources:
            try:
                stat = resolve_path(source.path, self.base_dir).stat()
                seen = (source.path, source.sha256, stat.st_size, stat.st_mtime_ns)
            except OSError:
                seen = (source.path, source.sha256, None, None)
            known = self._states.get(source.id)
            if known is None or known[0] != seen:
                known = self._states[source.id] = (
                    seen,
                    source_state(source, self.base_dir),
                )
            if known[1] != "ok":
                states[source.id] = known[1]
        return states

    def column_choices(self) -> list[tuple[str, ColumnRef]]:
        """Every column of every source, labelled for a choice box."""
        return column_choices(self.project, self.data)

    def array_choices(self) -> list[tuple[str, ArrayRef]]:
        """Every source as 2-D data, labelled for a choice box."""
        return array_choices(self.project)

    # --- selection ----------------------------------------------------------

    @property
    def selected(self) -> str | None:
        return self._selected

    def select(self, oid: str | None) -> None:
        if oid is not None and not self._exists(oid):
            oid = None
        if oid == self._selected:
            return
        self._selected = oid
        shown = self.figure
        if oid is not None:
            figure = self._figure_of(oid)
            if figure is not None:
                self.current_figure = figure.id
        self.selection_changed.emit(oid)
        if self.figure is not shown:
            self.figure_changed.emit()

    @property
    def figure(self) -> Figure | None:
        """The figure shown in the preview."""
        for figure in self.project.figures:
            if figure.id == self.current_figure:
                return figure
        return self.project.figures[0] if self.project.figures else None

    # --- internals ----------------------------------------------------------

    def _set(self, project: Project, path: Path | None) -> None:
        self.project = project
        self.path = path
        self.history = History(project)
        self._data: DataProvider | None = None
        self._data_sources: list | None = None
        self._states: dict[str, tuple[tuple, str]] = {}
        """Per source: what its file looked like, and its state then."""
        self._selected: str | None = None
        self.allow_preview = False
        """Whether tools may return an image of the figure; it shows the data."""
        self.current_figure: str | None = (
            project.figures[0].id if project.figures else None
        )

    def _after_change(self) -> None:
        if self._selected is not None and not self._exists(self._selected):
            self._selected = None
            self.selection_changed.emit(None)
        self.changed.emit()
        self.state_changed.emit()

    def _exists(self, oid: str) -> bool:
        axis = split_axis(oid)
        try:
            obj = find(self.project, axis[0] if axis else oid)
        except CommandError:
            return False
        return axis is None or getattr(obj, axis[1], None) is not None

    def _figure_of(self, oid: str) -> Figure | None:
        axis = split_axis(oid)
        if axis is not None:
            oid = axis[0]
        for figure in self.project.figures:
            if figure.id == oid:
                return figure
            for axes in figure.axes:
                if axes.id == oid or any(a.id == oid for a in axes.artists):
                    return figure
        return None


def _new_project() -> Project:
    return Project(figscribe_version=__version__, figures=[Figure()])
