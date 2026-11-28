"""The DataProvider the renderer reads through, backed by the project's files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from figscribe.io.csvfile import CsvTable, read_csv
from figscribe.io.errors import DataChangedError, DataError
from figscribe.io.files import resolve_path
from figscribe.io.hdf5file import Hdf5Table
from figscribe.io.numpyfile import read_numpy
from figscribe.io.sheetfile import SheetTable, read_sheet
from figscribe.model import (
    BY_COLUMN_SOURCES,
    ArrayRef,
    ColumnRef,
    CsvSource,
    DataSource,
    Hdf5Source,
    NumpySource,
    Project,
    SheetSource,
)

if TYPE_CHECKING:  # the renderer raises DataError, so it imports this package
    from figscribe.render import DataProvider


def load_data(project: Project, base_dir: str | Path) -> DataProvider:
    """Return a provider that reads each source on first use and caches it.

    A ColumnRef gives one column; an ArrayRef a whole table (CSV) or array
    (NumPy, HDF5) as 2-D data for images and colour meshes.

    Every file is checked against its recorded hash before it is parsed, and
    the bytes that were hashed are the bytes that get parsed. A changed file
    raises DataChangedError: plotting it silently would break the promise that
    a project and its generated script reproduce the same figure.
    """
    sources = {s.id: s for s in project.sources}
    tables: dict[tuple[str, str | None], np.ndarray] = {}
    opened: dict[str, CsvTable | SheetTable | Hdf5Table] = {}
    files: dict[tuple[str, str], bytes] = {}
    """{(path, hash): contents} of the HDF5 files, which several groups of one
    file share."""
    columns: dict[tuple[str, int], np.ndarray] = {}

    def table(source: DataSource, key: str | None = None) -> np.ndarray:
        if (source.id, key) not in tables:
            loaded = _load(source, base_dir, key)
            loaded.flags.writeable = False  # shared by every reference into it
            tables[source.id, key] = loaded
        return tables[source.id, key]

    def by_column(
        source: CsvSource | SheetSource | Hdf5Source,
    ) -> CsvTable | SheetTable | Hdf5Table:
        if source.id not in opened:
            if isinstance(source, CsvSource):
                raw, name = _checked_bytes(source, base_dir)
                opened[source.id] = CsvTable(source, raw, name)
            elif isinstance(source, SheetSource):
                raw, name = _checked_bytes(source, base_dir)
                opened[source.id] = read_sheet(source, raw, name)
            else:
                key = (source.path, source.sha256)
                name = str(resolve_path(source.path, base_dir))
                if key not in files:
                    files[key], name = _checked_bytes(source, base_dir)
                opened[source.id] = Hdf5Table(source, files[key], name)
        return opened[source.id]

    def resolve(ref: ColumnRef | ArrayRef) -> np.ndarray:
        source = sources.get(ref.source)
        if source is None:
            raise DataError(f"unknown data source {ref.source!r}")
        if isinstance(source, BY_COLUMN_SOURCES) or (
            isinstance(source, CsvSource) and source.time_columns
        ):
            # Column by column: only what is plotted has to be numbers.
            if isinstance(ref, ArrayRef):
                values = by_column(source).array()
            else:
                found = by_column(source)
                index = _column_index(source, ref.column, found.width)
                if (source.id, index) not in columns:
                    columns[source.id, index] = found.column(index)
                values = columns[source.id, index]
            values.flags.writeable = False
            return values
        if isinstance(ref, ArrayRef):
            return _as_recorded(source, table(source, ref.key))
        values = _as_recorded(source, table(source))
        if values.ndim == 1:
            values = values[:, np.newaxis]  # a 1-D array is one column
        return values[:, _column_index(source, ref.column, values.shape[1])]

    return resolve


def _as_recorded(source: DataSource, values: np.ndarray) -> np.ndarray:
    """A NumPy array of times that the project does not record as such, imported
    before figscribe read times, would give a figure the script cannot."""
    if (values.dtype.kind == "M") != bool(source.time_columns):
        raise DataError(
            f"{source.path} holds dates and times that the project does not record; "
            "import it again"
        )
    return values


def _load(
    source: CsvSource | NumpySource, base_dir: str | Path, key: str | None
) -> np.ndarray:
    raw, name = _checked_bytes(source, base_dir)
    if isinstance(source, NumpySource):
        return read_numpy(source, raw, name, key)
    return read_csv(source, raw, name)


def _checked_bytes(source: DataSource, base_dir: str | Path) -> tuple[bytes, str]:
    """(the file's contents, its path): the bytes that were imported."""
    path = resolve_path(source.path, base_dir)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DataError(f"cannot open {path}: {exc.strerror}") from exc

    if hashlib.sha256(raw).hexdigest() != source.sha256:
        raise DataChangedError(f"{path} has changed since it was imported")
    return raw, str(path)


def _column_index(source: DataSource, column: str | int, width: int) -> int:
    if isinstance(column, str):
        if column not in source.columns:
            known = ", ".join(repr(c) for c in source.columns)
            raise DataError(f"no column {column!r} in {source.path}; known are {known}")
        name, column = repr(column), source.columns.index(column)
    else:
        name = str(column)
    # A header can name more fields than the data rows have.
    if not 0 <= column < width:
        raise DataError(
            f"column {name} is out of range: {source.path} has {width} columns"
        )
    return column
