"""A recovery file for work not yet saved (roadmap E2, decision 0063).

While a project has unsaved changes, the window writes it every minute to
`<project>.figscribe.autosave`, next to the project; an untitled project goes to
the program's data folder, with its data paths made absolute. A clean save or a
clean close removes the file; one that is left was left by a crash, and the next
time the project is opened it is offered.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from figscribe.io.files import resolve_path
from figscribe.model import Project, dumps, loads

INTERVAL_MS = 60_000
SUFFIX = ".autosave"
UNTITLED_FOLDER: Path | None = None
"""Where an untitled project's recovery file goes; None asks the system when it
is needed, after the application's name is set. Tests point it elsewhere."""


def untitled_folder() -> Path:
    if UNTITLED_FOLDER is not None:
        return UNTITLED_FOLDER
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    return Path(base or Path.home() / ".figscribe") / "recovery"


def recovery_file(path: Path | None) -> Path:
    """The recovery file of the project saved at `path`, or of an untitled one."""
    if path is None:
        return untitled_folder() / f"untitled.figscribe{SUFFIX}"
    return path.with_name(path.name + SUFFIX)


def write(project: Project, path: Path | None, base_dir: Path) -> None:
    """Write the recovery file; the folder may not take it (OSError)."""
    written = project.model_copy(deep=True)
    if path is None:  # opened from anywhere later: the data is named in full
        for source in written.sources:
            source.path = str(resolve_path(source.path, base_dir))
    target = recovery_file(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        temporary.write_bytes(dumps(written).encode("utf-8"))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def discard(path: Path | None) -> None:
    """Remove the recovery file, if there is one and it may be removed."""
    try:
        recovery_file(path).unlink(missing_ok=True)
    except OSError:
        pass


def pending(path: Path | None) -> Path | None:
    """The recovery file that holds work newer than the project file at `path`;
    None if there is none. A file older than the project was left by a session
    that saved after it and is removed."""
    found = recovery_file(path)
    if not found.is_file():
        return None
    if path is not None and path.is_file():
        if found.stat().st_mtime <= path.stat().st_mtime:
            discard(path)
            return None
    return found


def load(found: Path) -> Project:
    """The project in a recovery file."""
    return loads(found.read_text(encoding="utf-8"))
