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
from figscribe.io import DataError, load_data
from figscribe.model import ColumnRef, Figure, Project, dumps, loads
from figscribe.render import DataProvider


class Document(QObject):
    changed = Signal()
    """The model changed: through a command, undo, redo, or a new file."""
    selection_changed = Signal(object)
    """The selected object id, or None."""
    state_changed = Signal()
    """Path or saved state changed; the window title follows it."""

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

    def column_choices(self) -> list[tuple[str, ColumnRef]]:
        """Every column of every source, labelled for a choice box.

        Columns are named where the file has a header, numbered otherwise;
        for a source without names the file is read to count its columns.
        """
        choices = []
        for source in self.project.sources:
            columns: list[str | int] = list(source.columns)
            if not columns:
                columns = list(range(self._width(source)))
            for column in columns:
                ref = ColumnRef(source=source.id, column=column)
                choices.append((f"{Path(source.path).name}: {column}", ref))
        return choices

    def _width(self, source) -> int:
        """Number of columns of a source; 0 if it cannot be read."""
        width = 0
        while True:
            try:
                self.data(ColumnRef(source=source.id, column=width))
            except DataError:
                return width
            width += 1

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
        if oid is not None:
            figure = self._figure_of(oid)
            if figure is not None:
                self.current_figure = figure.id
        self.selection_changed.emit(oid)

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
        self._selected: str | None = None
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
        try:
            find(self.project, oid)
        except CommandError:
            return False
        return True

    def _figure_of(self, oid: str) -> Figure | None:
        for figure in self.project.figures:
            if figure.id == oid:
                return figure
            for axes in figure.axes:
                if axes.id == oid or any(a.id == oid for a in axes.artists):
                    return figure
        return None


def _new_project() -> Project:
    return Project(figscribe_version=__version__, figures=[Figure()])
