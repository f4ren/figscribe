"""The undo/redo history of one project."""

from __future__ import annotations

from figscribe.commands.core import Command, CommandError
from figscribe.model import Project


class History:
    """Applies commands to a project and keeps them for undo and redo.

    Deliberately free of Qt: the GUI calls it and re-renders afterwards, and
    everything else that changes a project (tests, a later natural-language
    front end) goes through the same path.
    """

    def __init__(self, project: Project) -> None:
        self.project = project
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._clean: int | None = 0
        """Depth of the undo stack at the last save; None once unreachable."""

    def push(self, command: Command) -> None:
        """Apply `command` and record it. Raises, recording nothing, if it fails."""
        command.apply(self.project)
        if self._clean is not None and self._clean > len(self._undo):
            self._clean = None  # the saved state was on the redo stack
        self._undo.append(command)
        self._redo.clear()

    def undo(self) -> None:
        if not self._undo:
            raise CommandError("nothing to undo")
        command = self._undo.pop()
        command.revert(self.project)
        self._redo.append(command)

    def redo(self) -> None:
        if not self._redo:
            raise CommandError("nothing to redo")
        command = self._redo.pop()
        command.apply(self.project)
        self._undo.append(command)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_text(self) -> str | None:
        return self._undo[-1].description if self._undo else None

    @property
    def redo_text(self) -> str | None:
        return self._redo[-1].description if self._redo else None

    def mark_clean(self) -> None:
        """Record the current state as saved."""
        self._clean = len(self._undo)

    @property
    def is_clean(self) -> bool:
        """True when the project equals its last saved state."""
        return self._clean == len(self._undo)
