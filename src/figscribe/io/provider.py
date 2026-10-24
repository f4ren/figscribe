"""The DataProvider the renderer reads through, backed by the project's files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from figscribe.io.csvfile import ENCODING, read_csv
from figscribe.io.errors import DataChangedError, DataError
from figscribe.io.files import resolve_path
from figscribe.io.numpyfile import read_numpy
from figscribe.model import (
    ArrayRef,
    ColumnRef,
    CsvSource,
    DataSource,
    NumpySource,
    Project,
)

if TYPE_CHECKING:  # the renderer raises DataError, so it imports this package
    from figscribe.render import DataProvider


def load_data(project: Project, base_dir: str | Path) -> DataProvider:
    """Return a provider that reads each source on first use and caches it.

    A ColumnRef gives one column; an ArrayRef a whole table (CSV) or array
    (NumPy) as 2-D data for images and colour meshes.

    Every file is checked against its recorded hash before it is parsed, and
    the bytes that were hashed are the bytes that get parsed. A changed file
    raises DataChangedError: plotting it silently would break the promise that
    a project and its generated script reproduce the same figure.
    """
    sources = {s.id: s for s in project.sources}
    tables: dict[tuple[str, str | None], np.ndarray] = {}

    def table(source: DataSource, key: str | None = None) -> np.ndarray:
        if (source.id, key) not in tables:
            loaded = _load(source, base_dir, key)
            loaded.flags.writeable = False  # shared by every reference into it
            tables[source.id, key] = loaded
        return tables[source.id, key]

    def resolve(ref: ColumnRef | ArrayRef) -> np.ndarray:
        source = sources.get(ref.source)
        if source is None:
            raise DataError(f"unknown data source {ref.source!r}")
        if isinstance(ref, ArrayRef):
            return table(source, ref.key)
        values = table(source)
        if values.ndim == 1:
            values = values[:, np.newaxis]  # a 1-D array is one column
        return values[:, _column_index(source, ref.column, values.shape[1])]

    return resolve


def _load(source: DataSource, base_dir: str | Path, key: str | None) -> np.ndarray:
    if not isinstance(source, CsvSource | NumpySource):
        raise NotImplementedError(
            f"reading {source.format!r} sources is not implemented yet"
        )

    path = resolve_path(source.path, base_dir)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DataError(f"cannot open {path}: {exc.strerror}") from exc

    if hashlib.sha256(raw).hexdigest() != source.sha256:
        raise DataChangedError(f"{path} has changed since it was imported")
    if isinstance(source, NumpySource):
        return read_numpy(source, raw, str(path), key)
    return read_csv(source, raw.decode(ENCODING), str(path))


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
