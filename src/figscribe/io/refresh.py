"""A data file that changed or moved after it was imported.

`load_data` refuses such a file, so that a figure never quietly shows other
data than its script reads. These functions tell what happened, say what
changed, and take the file as it is now or where it went, as one command
that can be undone.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Literal

from figscribe.commands import Command, CommandError, Macro, SetField, find
from figscribe.io.csvfile import csv_source
from figscribe.io.errors import DataError
from figscribe.io.files import resolve_path, sha256_of
from figscribe.io.numpyfile import numpy_source
from figscribe.io.provider import load_data
from figscribe.model import ArrayRef, CsvSource, DataSource, NumpySource, Project

RECORDED = ("path", "sha256", "columns", "row_count")
"""What importing a file records about it, as opposed to how it is read."""


def source_state(
    source: DataSource, base_dir: str | Path
) -> Literal["ok", "changed", "missing"]:
    """Whether the source's file is still the one that was imported."""
    path = resolve_path(source.path, base_dir)
    if not path.is_file():
        return "missing"
    return "ok" if sha256_of(path) == source.sha256 else "changed"


def reread(
    source: DataSource, base_dir: str | Path, path: str | Path | None = None
) -> DataSource:
    """`source` as importing its file again would record it, read the way it
    is read now; from `path` instead, for a file that moved. A DataError if
    the file cannot be read that way."""
    if isinstance(source, CsvSource):
        describe = csv_source
    elif isinstance(source, NumpySource):
        describe = numpy_source
    else:
        raise DataError(f"reading {source.format!r} sources is not implemented yet")
    target = Path(path) if path is not None else resolve_path(source.path, base_dir)
    # Every reading option the source has, so that a new one is kept too;
    # the first two parameters are the file and the project's directory.
    options = {
        name: getattr(source, name)
        for name in list(inspect.signature(describe).parameters)[2:]
        if name in type(source).model_fields
    }
    try:
        fresh = describe(target, base_dir, **options)
    except OSError as exc:
        raise DataError(f"cannot open {target}: {exc.strerror}") from exc
    new = source.model_copy(update={name: getattr(fresh, name) for name in RECORDED})
    # Parse all of it now: a version that cannot be plotted is refused here.
    load_data(Project(sources=[new]), base_dir)(ArrayRef(source=new.id))
    return new


def use_new_version(
    project: Project,
    source_id: str,
    base_dir: str | Path,
    path: str | Path | None = None,
) -> Command:
    """Take the source's file as it is now, or from `path` where it moved to.

    A DataError, changing nothing, if it cannot be read as before.
    """
    source = find(project, source_id)
    if not isinstance(source, CsvSource | NumpySource):
        raise CommandError(f"{source_id!r} is not a data file")
    new = reread(source, base_dir, path)
    name = Path(source.path).name
    return Macro(
        f"Locate {name}" if path is not None else f"Use the new version of {name}",
        [
            SetField(source.id, (field,), getattr(new, field))
            for field in RECORDED
            if getattr(new, field) != getattr(source, field)
        ],
    )


def describe_change(old: DataSource, new: DataSource) -> str:
    """Rows and columns before and after, in a few lines."""
    before = "unknown" if old.row_count is None else str(old.row_count)
    lines = [f"{before} → {new.row_count} rows"]
    gone = [c for c in old.columns if c not in new.columns]
    added = [c for c in new.columns if c not in old.columns]
    if gone:
        lines.append(f"No longer has the columns {', '.join(gone)}")
    if added:
        lines.append(f"New columns {', '.join(added)}")
    if new.columns and not gone and not added:
        lines.append(f"Same columns: {', '.join(new.columns)}")
    return "\n".join(lines)
