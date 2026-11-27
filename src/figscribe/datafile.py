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
from figscribe.io.refresh import RECORDED, reread
from figscribe.model import (
    ArtistBase,
    ColumnRef,
    CsvSource,
    DataSource,
    FitCurve,
    NumpySource,
    Project,
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

    name: str
    plots: list[str]
    """What the plots that use it are called."""
    default: str | None
    """The column of the other file at the same place; None if it has none."""


def columns_to_choose(
    project: Project, source_id: str, base_dir: str | Path, path: str | Path
) -> tuple[list[MissingColumn], list[str]]:
    """The columns to find a place for in the file at `path`, and the columns it
    has. None for a file without column names, whose columns go by number.

    A DataError if the file cannot be read the way the old one was.
    """
    same_file = _same_file(project, source_id, base_dir)
    missing: dict[str, MissingColumn] = {}
    columns: list[str] = []
    for each in same_file:
        new = _read(each, base_dir, Path(path))
        columns = new.columns
        for artist in _artists(project):
            for _, ref in column_refs(artist):
                name = ref.column
                if ref.source != each.id or not isinstance(name, str):
                    continue
                if not new.columns or name in new.columns:
                    continue
                at = each.columns.index(name) if name in each.columns else None
                default = (
                    new.columns[at]
                    if at is not None and at < len(new.columns)
                    else None
                )
                found = missing.setdefault(name, MissingColumn(name, [], default))
                if _name(artist) not in found.plots:
                    found.plots.append(_name(artist))
    order = [name for each in same_file for name in each.columns]
    return sorted(
        missing.values(),
        key=lambda m: order.index(m.name) if m.name in order else len(order),
    ), columns


def use_another_file(
    project: Project,
    source_id: str,
    base_dir: str | Path,
    path: str | Path,
    columns: Mapping[str, str | None] | None = None,
) -> Swap:
    """Take the file at `path` in the place of the source's, in every source
    read from that file (the arrays of an .npz file), as one command. `columns`
    says which column of the new file takes the place of which old one.

    A DataError, changing nothing, if the file cannot be read the way the old
    one was.
    """
    same_file = _same_file(project, source_id, base_dir)
    old = Path(find(project, source_id).path).name
    steps: list[Command] = []
    for each in same_file:
        new = _read(each, base_dir, Path(path))
        steps += [
            SetField(each.id, (field,), getattr(new, field))
            for field in RECORDED
            if getattr(new, field) != getattr(each, field)
        ]
    if not steps:
        raise DataError(f"{Path(path).name} is the file already used")

    staging = project.model_copy(deep=True)
    for step in steps:
        step.apply(staging)
    ids = {each.id for each in same_file}

    def change(step: Command) -> None:
        step.apply(staging)
        steps.append(step)

    for artist in _artists(staging):
        for field, ref in column_refs(artist):
            new = (columns or {}).get(ref.column) if ref.source in ids else None
            if new is not None:
                change(
                    SetField(
                        artist.id, (field,), ColumnRef(source=ref.source, column=new)
                    )
                )
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


def _same_file(
    project: Project, source_id: str, base_dir: str | Path
) -> list[CsvSource | NumpySource]:
    """Every source read from the file the source `source_id` is read from."""
    source = find(project, source_id)
    if not isinstance(source, CsvSource | NumpySource):
        raise CommandError(f"{source_id!r} is not a data file")
    return [
        other
        for other in project.sources
        if resolve_path(other.path, base_dir) == resolve_path(source.path, base_dir)
        and isinstance(other, CsvSource | NumpySource)
    ]


def _read(source: DataSource, base_dir: str | Path, path: Path) -> DataSource:
    """The file at `path`, read as `source` is."""
    if isinstance(source, NumpySource) and path.suffix.lower() != f".{source.format}":
        raise DataError(
            f"{path.name} is not a .{source.format} file, which "
            f"{Path(source.path).name} is read as"
        )
    try:
        return reread(source, base_dir, path)
    except DataError as exc:
        raise DataError(
            f"{path.name} cannot be read the way {Path(source.path).name} is "
            f"({_how(source)}): {exc}"
        ) from exc


def _how(source: CsvSource | NumpySource) -> str:
    """What decides whether a file can be read, as the panel shows it."""
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
