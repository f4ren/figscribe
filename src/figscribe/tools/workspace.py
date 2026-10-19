"""What the tools act on: a project with its history, data and selection.

The GUI's Document is one workspace; `ProjectWorkspace` is another, without
Qt, for tests and for working on a project file without a window.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np

from figscribe.commands import Command, History
from figscribe.io import DataError, load_data
from figscribe.model import ColumnRef, Figure, Project

DataProvider = Callable[[ColumnRef], np.ndarray]


class Workspace(Protocol):
    project: Project
    history: History
    allow_preview: bool
    """Whether tools may return an image of the figure, which shows the data."""

    @property
    def data(self) -> DataProvider: ...

    @property
    def base_dir(self) -> Path:
        """Where the project's relative data paths start."""
        ...

    @property
    def selected(self) -> str | None: ...

    @property
    def figure(self) -> Figure | None: ...

    def push(self, command: Command) -> None: ...

    def undo(self) -> None: ...


class ProjectWorkspace:
    """A workspace without a GUI: a project, its history and its data files."""

    def __init__(self, project: Project, base_dir: str | Path):
        self.project = project
        self.history = History(project)
        self.base_dir = Path(base_dir)
        self.allow_preview = False
        self.selected: str | None = None

    @property
    def data(self) -> DataProvider:
        return load_data(self.project, self.base_dir)

    @property
    def figure(self) -> Figure | None:
        return self.project.figures[0] if self.project.figures else None

    def push(self, command: Command) -> None:
        self.history.push(command)

    def undo(self) -> None:
        self.history.undo()


def column_choices(project: Project, data: DataProvider) -> list[tuple[str, ColumnRef]]:
    """Every column of every source, labelled "file: column".

    Columns are named where the file has a header, numbered otherwise; for a
    source without names the file is read to count its columns.
    """
    choices = []
    for source in project.sources:
        columns: list[str | int] = list(source.columns)
        if not columns:
            columns = list(range(_width(source.id, data)))
        for column in columns:
            ref = ColumnRef(source=source.id, column=column)
            choices.append((f"{Path(source.path).name}: {column}", ref))
    return choices


def _width(source_id: str, data: DataProvider) -> int:
    """Number of columns of a source; 0 if it cannot be read."""
    width = 0
    while True:
        try:
            data(ColumnRef(source=source_id, column=width))
        except DataError:
            return width
        width += 1
