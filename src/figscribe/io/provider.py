"""The DataProvider the renderer reads through, backed by the project's files."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from figscribe.io.csvfile import ENCODING, read_csv
from figscribe.io.errors import DataChangedError, DataError
from figscribe.io.files import resolve_path
from figscribe.model import ColumnRef, CsvSource, DataSource, Project
from figscribe.render import DataProvider


def load_data(project: Project, base_dir: str | Path) -> DataProvider:
    """Return a provider that reads each source on first use and caches it.

    Every file is checked against its recorded hash before it is parsed, and
    the bytes that were hashed are the bytes that get parsed. A changed file
    raises DataChangedError: plotting it silently would break the promise that
    a project and its generated script reproduce the same figure.
    """
    sources = {s.id: s for s in project.sources}
    tables: dict[str, np.ndarray] = {}

    def resolve(ref: ColumnRef) -> np.ndarray:
        source = sources.get(ref.source)
        if source is None:
            raise DataError(f"unknown data source {ref.source!r}")
        if source.id not in tables:
            table = _load(source, base_dir)
            table.flags.writeable = False  # shared by every reference into it
            tables[source.id] = table
        table = tables[source.id]
        return table[:, _column_index(source, ref.column, table.shape[1])]

    return resolve


def _load(source: DataSource, base_dir: str | Path) -> np.ndarray:
    if not isinstance(source, CsvSource):
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
    return read_csv(source, raw.decode(ENCODING), str(path))


def _column_index(source: DataSource, column: str | int, width: int) -> int:
    if isinstance(column, int):
        if not 0 <= column < width:
            raise DataError(
                f"column {column} is out of range: {source.path} has {width} columns"
            )
        return column
    if column not in source.columns:
        known = ", ".join(repr(c) for c in source.columns)
        raise DataError(f"no column {column!r} in {source.path}; known are {known}")
    return source.columns.index(column)
