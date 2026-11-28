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

from pydantic import ValidationError

from figscribe.commands import Command, CommandError, Macro, SetField, find
from figscribe.io.csvfile import csv_source
from figscribe.io.errors import DataError
from figscribe.io.files import resolve_path, sha256_of
from figscribe.io.hdf5file import hdf5_source, only_like
from figscribe.io.numpyfile import numpy_source
from figscribe.io.provider import load_data
from figscribe.io.sheetfile import sheet_names, sheet_source
from figscribe.model import (
    BY_COLUMN_SOURCES,
    FILE_SOURCES,
    ArrayRef,
    CsvSource,
    DataSource,
    Hdf5Source,
    NumpySource,
    Project,
    SheetSource,
)
from figscribe.model.validate import file_refs

RECORDED = ("path", "sha256", "columns", "row_count")
"""What importing a file records about it, as opposed to how it is read."""


def part_field(source: object) -> str | None:
    """The field that names which part of its file a source reads; None for a
    file that is read whole."""
    if isinstance(source, SheetSource):
        return "sheet"
    return "dataset" if isinstance(source, Hdf5Source) else None


def recorded(source: DataSource) -> tuple[str, ...]:
    """The fields another version of the source's file may set."""
    if isinstance(source, Hdf5Source):
        return (*RECORDED, "dataset")  # groups are renamed from run to run
    if isinstance(source, SheetSource):
        # Another file may be of another format, start in another column, and
        # have only one sheet, of another name.
        return (*RECORDED, "format", "first_column", "sheet")
    return RECORDED


def source_state(
    source: DataSource, base_dir: str | Path
) -> Literal["ok", "changed", "missing"]:
    """Whether the source's file is still the one that was imported."""
    path = resolve_path(source.path, base_dir)
    if not path.is_file():
        return "missing"
    return "ok" if sha256_of(path) == source.sha256 else "changed"


def reread(
    source: DataSource,
    base_dir: str | Path,
    path: str | Path | None = None,
    *,
    part: str | None = None,
) -> DataSource:
    """`source` as importing its file again would record it, read the way it
    is read now; from `path` instead, for a file that moved, and from `part`
    instead of the source's sheet or dataset. A DataError if the file cannot be
    read that way."""
    describe = _describer(source)
    target = Path(path) if path is not None else resolve_path(source.path, base_dir)
    options = {name: getattr(source, name) for name in reading_options(source)}
    if part is not None:
        options[part_field(source)] = part
    try:
        fresh = describe(target, base_dir, **options)
    except OSError as exc:
        raise DataError(f"cannot open {target}: {exc.strerror}") from exc
    new = source.model_copy(
        update={name: getattr(fresh, name) for name in recorded(source)}
    )
    # Parse all of it now: a version that cannot be plotted is refused here.
    # A sheet or an HDF5 file may hold anything beside what is plotted; see
    # `check_plotted`.
    if not isinstance(new, BY_COLUMN_SOURCES):
        load_data(Project(sources=[new]), base_dir)(ArrayRef(source=new.id))
    return new


def sole_part(source: DataSource, path: Path) -> str | None:
    """Where the source's sheet or dataset is not in the file at `path`, the one
    that is meant: the only sheet, or the only entry with the source's columns.
    Sheets and groups of lab files are often named after the run or the day."""
    if part_field(source) is None:
        return None
    try:
        raw = path.read_bytes()
        if isinstance(source, Hdf5Source):
            return only_like(source, raw, path.name)
        names = sheet_names(raw, path.name)
    except (OSError, DataError):
        return None  # reading it says why
    return names[0] if len(names) == 1 and source.sheet not in names else None


def check_plotted(project: Project, source_id: str, base_dir: str | Path) -> None:
    """A DataError if a column of the source `source_id` that a figure plots
    cannot be read as numbers, where its columns are read one at a time. A
    column that is gone is left to the list of problems."""
    source = find(project, source_id)
    if not isinstance(source, BY_COLUMN_SOURCES):
        return
    data = load_data(project, base_dir)
    for figure in project.figures:
        for axes in figure.axes:
            for artist in axes.artists:
                for ref in file_refs(artist):
                    if ref.source == source_id and (
                        isinstance(ref, ArrayRef)
                        or not isinstance(ref.column, str)
                        or ref.column in source.columns
                    ):
                        data(ref)


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
    if not isinstance(source, FILE_SOURCES):
        raise CommandError(f"{source_id!r} is not a data file")
    target = Path(path) if path is not None else resolve_path(source.path, base_dir)
    new = reread(source, base_dir, path, part=sole_part(source, target))
    staging = project.model_copy(deep=True)
    staging.sources = [new if s.id == new.id else s for s in staging.sources]
    check_plotted(staging, source_id, base_dir)
    name = Path(source.path).name
    return Macro(
        f"Locate {name}" if path is not None else f"Use the new version of {name}",
        [
            SetField(source.id, (field,), getattr(new, field))
            for field in recorded(source)
            if getattr(new, field) != getattr(source, field)
        ],
    )


OPTION_NAMES = {
    "delimiter": "separator",
    "decimal": "decimal mark",
    "header_row": "header line",
    "skip_rows": "number of lines skipped",
    "comment": "comment mark",
    "encoding": "text encoding",
    "array": "array",
    "sheet": "sheet",
    "dataset": "dataset",
}
"""What each reading option is called in the undo text."""


def reading_options(obj: object) -> tuple[str, ...]:
    """The fields that say how a data file is read; none for anything else."""
    if not isinstance(obj, FILE_SOURCES):
        return ()
    # The reader's options after the file and the project's directory, so
    # that a new one counts without being listed here.
    parameters = list(inspect.signature(_describer(obj)).parameters)[2:]
    return tuple(name for name in parameters if name in type(obj).model_fields)


def read_differently(
    project: Project, source_id: str, field: str, value: object, base_dir: str | Path
) -> Command:
    """Read the source's file with `field` set to `value`: one step that also
    takes the columns and rows the file then has.

    A DataError, changing nothing, if the file cannot be read that way, or is
    no longer the one imported: reading it again would take the new version
    without saying so.
    """
    source = find(project, source_id)
    if not isinstance(source, FILE_SOURCES):
        raise CommandError(f"{source_id!r} is not a data file")
    if field not in reading_options(source):
        raise CommandError(f"{field!r} is not how {source.path} is read")
    name = Path(source.path).name
    state = source_state(source, base_dir)
    if state == "changed":
        raise DataError(
            f"{name} has changed since it was imported; use its new version first"
        )
    if state == "missing":
        raise DataError(f"{name} is missing; locate it first")
    candidate = source.model_copy()
    try:
        setattr(candidate, field, value)
    except ValidationError as exc:
        reason = "; ".join(e["msg"] for e in exc.errors())
        raise CommandError(f"cannot set {field}: {reason}") from exc
    new = reread(candidate, base_dir)
    # As for a text file, a way of reading that makes no numbers of what is
    # plotted is refused; not another sheet or dataset, which one picks to see.
    if field != part_field(source):
        staging = project.model_copy(deep=True)
        staging.sources = [new if s.id == new.id else s for s in staging.sources]
        check_plotted(staging, source_id, base_dir)
    return Macro(
        f"Read {name} with another {OPTION_NAMES.get(field, field)}",
        [SetField(source.id, (field,), getattr(new, field))]
        + [
            SetField(source.id, (part,), getattr(new, part))
            for part in ("columns", "row_count", "first_column")
            if part in type(new).model_fields
            and getattr(new, part) != getattr(source, part)
        ],
    )


def _describer(source: DataSource):
    if isinstance(source, CsvSource):
        return csv_source
    if isinstance(source, NumpySource):
        return numpy_source
    if isinstance(source, SheetSource):
        return sheet_source
    return hdf5_source


def describe_change(old: DataSource, new: DataSource) -> str:
    """Rows and columns before and after, in a few lines."""
    before = "unknown" if old.row_count is None else str(old.row_count)
    lines = [f"{before} → {new.row_count} rows"]
    part = part_field(new)
    if part is not None and getattr(new, part) != getattr(old, part):
        lines.append(f"The {part} is now {getattr(new, part)!r}")
    gone = [c for c in old.columns if c not in new.columns]
    added = [c for c in new.columns if c not in old.columns]
    if gone:
        lines.append(f"No longer has the columns {', '.join(gone)}")
    if added:
        lines.append(f"New columns {', '.join(added)}")
    if new.columns and not gone and not added:
        lines.append(f"Same columns: {', '.join(new.columns)}")
    return "\n".join(lines)
