"""Use another file: a data file's place taken by a different one.

The new file is read the way the old one was, and what was worked out from
the old file's numbers goes over with it: each fit is run again, and one that
cannot be draws nothing instead of the old curve over other data; left-out
rows, which are row numbers of the old file, are taken back in. Settings in
the data's units, such as ranges and axis limits, are the user's and stay.

Not an assistant tool: the assistant must not point a source at other files on
the machine (decision 0007).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from figscribe.commands import Command, CommandError, Macro, SetField, find
from figscribe.io import DataError, load_data
from figscribe.io.files import resolve_path
from figscribe.io.refresh import check_plotted, recorded, reread, sole_sheet
from figscribe.io.sheetfile import FORMATS, sheet_names
from figscribe.model import (
    FILE_SOURCES,
    ArtistBase,
    ColumnRef,
    CsvSource,
    DataSource,
    FitCurve,
    NumpySource,
    Project,
    SheetSource,
)
from figscribe.model.validate import column_refs, data_refs, missing_columns
from figscribe.refits import guess_first, run_again


@dataclass
class Swap:
    command: Command
    notes: list[str]
    """What the user should know about it, a sentence each; often nothing."""


@dataclass
class MissingColumn:
    """A column that plots use and the other file has under no such name."""

    source: str
    """Id of the source: one file read twice may name its columns twice over."""
    name: str
    plots: list[str]
    """What the plots that use it are called."""
    choices: list[str]
    """The columns of the other file as this source reads it, each name once."""
    default: str | None
    """The column at the same place; None if there is none free to propose."""


def sheets_to_choose(
    project: Project, source_id: str, base_dir: str | Path, path: str | Path
) -> dict[str, list[str]]:
    """{sheet in use: the sheets of the file at `path`} where the user has to
    say which sheet takes its place: the file has none of that name, and it is
    not the one sheet in use for a file that has one sheet."""
    used = [
        each.sheet
        for each in _same_file(project, source_id, base_dir)
        if isinstance(each, SheetSource)
    ]
    if not used or Path(path).suffix.lower() not in FORMATS:
        return {}
    try:
        names = sheet_names(Path(path).read_bytes(), Path(path).name)
    except OSError as exc:
        raise DataError(f"cannot open {path}: {exc.strerror}") from exc
    missing = [sheet for sheet in dict.fromkeys(used) if sheet not in names]
    if len(names) == 1 and len(set(used)) == 1:
        return {}
    return {sheet: names for sheet in missing}


def columns_to_choose(
    project: Project,
    source_id: str,
    base_dir: str | Path,
    path: str | Path,
    sheets: Mapping[str, str] | None = None,
) -> list[MissingColumn]:
    """The columns to find a place for in the file at `path`. None for a file
    without column names, whose columns go by number.

    A DataError if the file cannot be read the way the old one was.
    """
    found: list[MissingColumn] = []
    same_file = _same_file(project, source_id, base_dir)
    for each in same_file:
        new = _read(each, base_dir, Path(path), _sheet(same_file, each, path, sheets))
        if not new.columns:
            continue
        choices = list(dict.fromkeys(new.columns))
        missing: dict[str, MissingColumn] = {}
        for artist in _artists(project):
            for _, ref in column_refs(artist):
                name = ref.column
                if ref.source != each.id or not isinstance(name, str):
                    continue
                if name in new.columns:
                    continue
                if name not in missing:
                    default = _at_the_same_place(each.columns, new.columns, name)
                    if default and not _numbers(new, default, base_dir):
                        default = None
                    missing[name] = MissingColumn(each.id, name, [], choices, default)
                if _name(artist) not in missing[name].plots:
                    missing[name].plots.append(_name(artist))
        order = {name: i for i, name in enumerate(each.columns)}
        found += sorted(missing.values(), key=lambda m: order.get(m.name, len(order)))
    return found


def _numbers(source: DataSource, column: str, base_dir: str | Path) -> bool:
    """Whether the column can be plotted."""
    data = load_data(Project(sources=[source]), base_dir)
    try:
        data(ColumnRef(source=source.id, column=column))
    except DataError:
        return False
    return True


def _at_the_same_place(old: list[str], new: list[str], name: str) -> str | None:
    """The new column where `name` was, to propose for it: not one that is one
    of the old columns still, going by its name."""
    at = old.index(name) if name in old else len(new)
    if at >= len(new) or new[at] in old:
        return None
    return new[at]


def use_another_file(
    project: Project,
    source_id: str,
    base_dir: str | Path,
    path: str | Path,
    columns: Mapping[tuple[str, str], str | None] | None = None,
    sheets: Mapping[str, str] | None = None,
) -> Swap:
    """Take the file at `path` in the place of the source's, in every source
    read from that file (the arrays of an .npz file), as one command. `columns`
    says, by source id and old name, which column of the new file takes a place.
    The file already used may be given again to place a column left out before.
    `sheets` says, by sheet in use, which sheet of the new file takes its place
    (see `sheets_to_choose`).

    A DataError, changing nothing, if the file cannot be read the way the old
    one was.
    """
    same_file = _same_file(project, source_id, base_dir)
    old = Path(find(project, source_id).path).name
    steps: list[Command] = []
    for each in same_file:
        new = _read(each, base_dir, Path(path), _sheet(same_file, each, path, sheets))
        steps += [
            SetField(each.id, (field,), getattr(new, field))
            for field in recorded(each)
            if getattr(new, field) != getattr(each, field)
        ]
    staging = project.model_copy(deep=True)
    for step in steps:
        step.apply(staging)
    ids = {each.id for each in same_file}
    swapped = bool(steps)  # not the file already used

    def change(step: Command) -> None:
        step.apply(staging)
        steps.append(step)

    for artist in _artists(staging):
        for field, ref in column_refs(artist):
            new = (columns or {}).get((ref.source, ref.column))
            if new is not None and ref.source in ids:
                change(
                    SetField(
                        artist.id, (field,), ColumnRef(source=ref.source, column=new)
                    )
                )
    for each in same_file:  # with the columns in their places
        try:
            check_plotted(staging, each.id, base_dir)
        except DataError as exc:
            raise DataError(f"{Path(path).name} cannot be used: {exc}") from exc
    if not steps:
        raise DataError(f"{Path(path).name} is the file already used")
    plots = [
        artist
        for artist in _artists(staging)
        if any(used in ids for _, used in data_refs(artist))
    ]
    notes = [
        f"The new file has no column {column.column}, which {_name(artist)} uses."
        for artist, _, column in missing_columns(staging)
        if column.source in ids
    ]

    if not swapped:  # only columns placed: the rows and fits are as they were
        return Swap(Macro(f"Use another file for {old}", steps), notes)
    taken_back = []
    for plot in plots:
        if getattr(plot, "left_out", None):
            taken_back.append(_name(plot))
            change(SetField(plot.id, ("left_out",), []))
            change(SetField(plot.id, ("left_out_note",), None))
    if taken_back:
        notes.append(
            f"The left-out rows of {', '.join(taken_back)} are taken back in: their "
            "numbers meant the old file."
        )

    targets = {plot.id for plot in plots}
    for fit in _artists(staging):
        if not isinstance(fit, FitCurve) or fit.target not in targets:
            continue
        if fit.result is None:
            continue
        data = load_data(staging, base_dir)
        again, why = run_again(staging, fit, data, guess_first(fit))
        if why is not None:
            change(SetField(fit.id, ("result",), None))
            subject = fit.label or "The fit"
            notes.append(f"{subject} is not fitted on the new data: {why}.")
        for step in again:
            change(step)
    return Swap(Macro(f"Use another file for {old}", steps), notes)


def _sheet(same_file: list, source: DataSource, path: str | Path, sheets) -> str | None:
    """The sheet of the new file that the source is read from; None to keep
    the one it has."""
    if not isinstance(source, SheetSource):
        return None
    if sheets and source.sheet in sheets:
        return sheets[source.sheet]
    used = {each.sheet for each in same_file if isinstance(each, SheetSource)}
    return sole_sheet(source, Path(path)) if len(used) == 1 else None


def _same_file(
    project: Project, source_id: str, base_dir: str | Path
) -> list[CsvSource | NumpySource | SheetSource]:
    """Every source read from the file the source `source_id` is read from."""
    source = find(project, source_id)
    if not isinstance(source, FILE_SOURCES):
        raise CommandError(f"{source_id!r} is not a data file")
    return [
        other
        for other in project.sources
        if resolve_path(other.path, base_dir) == resolve_path(source.path, base_dir)
        and isinstance(other, FILE_SOURCES)
    ]


def _read(
    source: DataSource, base_dir: str | Path, path: Path, sheet: str | None = None
) -> DataSource:
    """The file at `path`, read as `source` is."""
    if isinstance(source, SheetSource) and path.suffix.lower() not in FORMATS:
        raise DataError(
            f"{path.name} is not a spreadsheet, which {Path(source.path).name} is"
        )
    if isinstance(source, NumpySource) and path.suffix.lower() != f".{source.format}":
        raise DataError(
            f"{path.name} is not a .{source.format} file, which "
            f"{Path(source.path).name} is read as"
        )
    try:
        return reread(source, base_dir, path, sheet=sheet)
    except DataError as exc:
        raise DataError(
            f"{path.name} cannot be read the way {Path(source.path).name} is "
            f"({_how(source)}): {exc}"
        ) from exc


def _how(source: CsvSource | NumpySource | SheetSource) -> str:
    """What decides whether a file can be read, as the panel shows it."""
    if isinstance(source, SheetSource):
        header = "no row of names"
        if source.header_row is not None:
            header = f"names in row {source.header_row + 1}"
        return f"sheet {source.sheet!r}, {header}, rows skipped {source.skip_rows}"
    if isinstance(source, NumpySource):
        return f"array {source.array}" if source.array else "one array"
    if source.delimiter is None:
        separator = "split at spaces"
    else:
        separator = f"separator '{source.delimiter}'"
    if source.header_row is None:
        header = "no header line"
    else:
        header = f"header line {source.header_row + 1}"  # counted from 1 there
    return (
        f"{separator}, decimal mark '{source.decimal}', {header}, "
        f"lines skipped {source.skip_rows}"
    )


def _artists(project: Project) -> list[ArtistBase]:
    return [
        artist
        for figure in project.figures
        for axes in figure.axes
        for artist in axes.artists
    ]


def _name(artist: ArtistBase) -> str:
    return artist.label or f"the {artist.kind}"
