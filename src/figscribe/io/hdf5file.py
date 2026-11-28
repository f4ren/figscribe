"""HDF5 files (decision 0081).

A source is one entry of the file, named by its path:

- a group: the one-dimensional datasets of numbers in it are the columns, which
  need not be of one length;
- a table of records (a compound dataset): its fields of numbers;
- a one-dimensional dataset: one column;
- a two-dimensional dataset: columns by number, as for a NumPy array.

Only what the file itself holds is read. An external link, a virtual dataset
and values stored in a file beside it are refused: the file's hash says nothing
about them, and read from the hashed bytes in memory HDF5 would give other
values than the script reading from disk.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import h5py
import numpy as np

from figscribe.io.errors import DataError
from figscribe.io.files import sha256_of, stored_path
from figscribe.model import Hdf5Source

SUFFIXES = (".h5", ".hdf5", ".he5", ".nxs")
"""The file name endings that are read as HDF5."""


@dataclass(frozen=True)
class Entry:
    """A group or dataset of a file, and what choosing it as data gives."""

    path: str
    kind: str
    """"group", "table" (records), "column", "image" (two dimensions) or
    "other"."""
    shape: tuple[int, ...] | None = None
    """None for a group."""
    columns: list[str] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    """Values in each column."""
    rows: int = 0
    left_out: dict[str, str] = field(default_factory=dict)
    """{member or field that is no column: why}."""
    problem: str = ""
    """Why it cannot be chosen; "" if it can."""


def hdf5_source(
    path: str | Path, base_dir: str | Path, *, dataset: str | None = None
) -> Hdf5Source:
    """Describe an entry of an HDF5 file for the model: hash the file and find
    the columns. `dataset` None takes the first that looks like a table."""
    path = Path(path)
    raw = path.read_bytes()
    with _opened(raw, path.name) as file:
        if dataset is None:
            entry = likely(list(_walk(file)), path.name)
        else:
            entry = _chosen(file, _normal(dataset), path.name)
    return Hdf5Source(
        path=stored_path(path, base_dir),
        sha256=sha256_of(path),
        dataset=entry.path,
        holds=entry.kind,
        columns=entry.columns,
        row_count=entry.rows,
    )


def entries(raw: bytes, name: str) -> list[Entry]:
    """Every group and dataset of the file, each group before what it holds."""
    with _opened(raw, name) as file:
        return list(_walk(file))


def head(
    source: Hdf5Source, raw: bytes, rows: int, columns: int
) -> tuple[list[np.ndarray], int]:
    """The first `rows` values of the first `columns` columns, and how many
    columns there are: what a preview shows of data that may be large."""
    name = Path(source.path).name
    with _opened(raw, name) as file:
        found = _resolved(file, source.dataset, name)
        if source.holds == "image":
            values = found[:rows, :columns].astype(float)
            return list(values.T), found.shape[1]
        names = source.columns[:columns]
        if source.holds == "group":
            read = [
                _resolved(file, _join(source.dataset, n), name)[:rows] for n in names
            ]
        elif source.holds == "table":
            start = found[:rows]
            read = [start[n] for n in names]
        else:
            read = [found[:rows]]
        return [values.astype(float) for values in read], len(source.columns)


def has(raw: bytes, name: str, path: str) -> bool:
    """Whether the file has something at `path`, readable or not."""
    with _opened(raw, name) as file:
        return path in file


def like(source: Hdf5Source, raw: bytes, name: str) -> list[str]:
    """The entries that could take the place of the source's, those with all of
    its columns first."""
    found = [e for e in entries(raw, name) if not e.problem]
    if not source.columns:
        return [e.path for e in found if e.kind == "image"]
    wanted = set(source.columns)
    usable = [e for e in found if e.columns]
    usable.sort(key=lambda e: not wanted <= set(e.columns))  # stable
    return [e.path for e in usable]


def only_like(source: Hdf5Source, raw: bytes, name: str) -> str | None:
    """The one entry of the file that has the source's columns, where nothing is
    at the source's own path: groups are often named after the run or the day."""
    if has(raw, name, source.dataset):
        return None
    fitting = [
        e.path
        for e in entries(raw, name)
        if not e.problem
        and (
            set(source.columns) <= set(e.columns)
            if source.columns
            else e.kind == "image"
        )
    ]
    return fitting[0] if len(fitting) == 1 else None


def units(source: Hdf5Source, raw: bytes) -> list[str]:
    """The unit each column's dataset names in its attributes, "" for none.
    Fields of a table of records have no attributes of their own."""
    name = Path(source.path).name
    with _opened(raw, name) as file:
        found = _resolved(file, source.dataset, name)
        if isinstance(found, h5py.Group):
            return [
                _unit(_resolved(file, _join(source.dataset, column), name))
                for column in source.columns
            ]
        if found.dtype.names:
            return [""] * len(source.columns)
        return [_unit(found)] * len(source.columns)


class Hdf5Table:
    """The columns of one source, read from the file contents when asked for."""

    def __init__(self, source: Hdf5Source, raw: bytes, name: str):
        self.source = source
        self._raw = raw
        self._name = Path(name).name
        self._image: np.ndarray | None = None
        with _opened(raw, self._name) as file:
            found = _resolved(file, source.dataset, self._name)
            if isinstance(found, h5py.Group):
                self.kind, self.width = "group", len(source.columns)
            else:
                entry = _checked(_dataset_entry(found, source.dataset), self._name)
                self.kind = entry.kind
                self.width = len(source.columns)
                if entry.kind == "image":
                    self.width = entry.shape[1]
                elif entry.kind == "column":
                    self.width = 1
        # The script reads what the source records, so the two must agree.
        if self.kind != source.holds:
            raise DataError(
                f"{self._name}, {source.dataset}, is not what the project records"
            )

    def column(self, index: int) -> np.ndarray:
        """The column `index` of the table (from 0) as floats."""
        if self.kind == "image":
            return self.array()[:, index]
        source = self.source
        with _opened(self._raw, self._name) as file:
            path = source.dataset
            if self.kind == "group":
                path = _join(path, source.columns[index])
            found = _resolved(file, path, self._name)
            if self.kind == "table":
                column = source.columns[index]
                if column not in (found.dtype.names or ()):
                    raise DataError(f"{self._name}, {path}, has no field {column!r}")
                why = _no_numbers(found.dtype[column])
                values = None if why else found[()][column]
            else:
                why = _no_column(found)
                values = None if why else found[()]
            if why:
                raise DataError(f"cannot plot {self._name}, {path}: {why}")
        return values.astype(float)

    def array(self) -> np.ndarray:
        """Every column, as 2-D data for images and color meshes; a single
        dataset as it is."""
        if self.kind in ("image", "column"):
            if self._image is None:
                with _opened(self._raw, self._name) as file:
                    found = _resolved(file, self.source.dataset, self._name)
                    self._image = found[()].astype(float)
            return self._image
        columns = [self.column(i) for i in range(self.width)]
        if len({len(values) for values in columns}) > 1:
            raise DataError(
                f"{self._name}, {self.source.dataset}, holds datasets of different "
                "lengths, which cannot be taken as one table"
            )
        return np.column_stack(columns)


class _Refused(DataError):
    """An entry whose values are not in the file; `why` finishes a sentence."""

    def __init__(self, name: str, path: str, why: str):
        super().__init__(f"cannot plot {name}, {path}: {why}")
        self.why = why


@contextmanager
def _opened(raw: bytes, name: str) -> Iterator[h5py.File]:
    """The file contents `raw`, with every failure of the library as a
    DataError: it raises OSError, KeyError, RuntimeError and more."""
    try:
        with h5py.File(io.BytesIO(raw), "r") as file:
            yield file
    except (DataError, MemoryError):
        raise
    except Exception as exc:
        raise DataError(f"cannot read {name}: {exc}") from exc


def _normal(path: str) -> str:
    return "/" + "/".join(part for part in path.split("/") if part)


def _join(path: str, member: str) -> str:
    return f"{path.rstrip('/')}/{member}"


def _resolved(file: h5py.File, path: str, name: str):
    """The group or dataset at `path`, if its values are in this file."""
    try:
        found = file[path]
    except (KeyError, RuntimeError, OSError, ValueError) as exc:
        if path in file or file.get(path, getlink=True) is not None:
            raise _Refused(name, path, "it is a link that leads nowhere") from exc
        raise DataError(f"{name} has no {path!r}") from exc
    if found.file.id != file.id:
        raise _Refused(
            name, path, "it is in another file, which an external link leads to"
        )
    if isinstance(found, h5py.Dataset):
        if found.is_virtual:
            raise _Refused(
                name, path, "it is a virtual dataset, whose values are in other files"
            )
        if found.external is not None:
            raise _Refused(name, path, "its values are stored outside the file")
    return found


def _no_numbers(dtype: np.dtype) -> str:
    """Why values of `dtype` are no numbers to plot; "" if they are."""
    if h5py.check_enum_dtype(dtype):
        return "it holds named values (an enumeration)"
    if h5py.check_string_dtype(dtype) or dtype.kind in "SU":
        return "it holds text"
    if dtype.names:
        return "it holds records"
    if dtype.subdtype:
        return "it holds an array in each place"
    if dtype.kind == "b":
        return "it holds true or false"
    if dtype.kind == "c":
        return "it holds complex numbers"
    if dtype.kind not in "iuf":
        return "it holds no numbers"
    return ""


def _unreadable(dataset: h5py.Dataset) -> str:
    """Why the values cannot be read; "" if the first one can."""
    try:
        dataset[:1]
    except MemoryError:
        raise
    except Exception as exc:
        return (
            "it cannot be read, perhaps because of the compression it was written "
            f"with ({exc})"
        )
    return ""


def _no_column(dataset) -> str:
    """Why `dataset` is no column; "" if it is."""
    if not isinstance(dataset, h5py.Dataset):
        return "it is not a dataset"
    if dataset.shape is None:
        return "it is empty"
    if dataset.ndim == 0:
        return "it holds one value only"
    if dataset.ndim > 1:
        return f"it has {dataset.ndim} dimensions"
    if why := _no_numbers(dataset.dtype):
        return why
    if not dataset.shape[0]:
        return "it is empty"
    return _unreadable(dataset)


def _dataset_entry(dataset: h5py.Dataset, path: str) -> Entry:
    shape = dataset.shape
    if shape is not None and dataset.dtype.names:
        if len(shape) != 1:
            why = f"it holds records in {len(shape)} dimensions"
            return Entry(path, "other", shape, problem=why)
        left_out = {
            name: why
            for name in dataset.dtype.names
            if (why := _no_numbers(dataset.dtype[name]))
        }
        columns = [name for name in dataset.dtype.names if name not in left_out]
        problem = "it holds no numbers" if not columns else ""
        problem = problem or ("it is empty" if not shape[0] else _unreadable(dataset))
        return Entry(
            path,
            "table",
            shape,
            columns,
            [shape[0]] * len(columns),
            shape[0],
            left_out,
            problem,
        )
    if shape is not None and len(shape) == 2:
        problem = _no_numbers(dataset.dtype)
        problem = problem or ("it is empty" if not all(shape) else _unreadable(dataset))
        return Entry(path, "image", shape, rows=shape[0], problem=problem)
    if why := _no_column(dataset):
        return Entry(path, "other", shape, problem=why)
    leaf = path.rsplit("/", 1)[-1]
    return Entry(path, "column", shape, [leaf], [shape[0]], shape[0])


def _group_entry(file: h5py.File, group: h5py.Group, path: str) -> Entry:
    columns, lengths, left_out = [], [], {}
    for member in group:
        try:
            found = _resolved(file, _join(path, member), "")
        except _Refused as refused:
            left_out[member] = refused.why
            continue
        if not isinstance(found, h5py.Dataset):
            continue  # a group is an entry of its own
        if why := _no_column(found):
            left_out[member] = why
        else:
            columns.append(member)
            lengths.append(found.shape[0])
    problem = "" if columns else "it holds no one-dimensional numbers"
    rows = max(lengths, default=0)
    return Entry(path, "group", None, columns, lengths, rows, left_out, problem)


def _walk(file: h5py.File) -> Iterator[Entry]:
    """Every entry, depth first. A group is entered where it is held, not where
    a link points to it, and once: groups may hold one another."""
    seen = {file["/"].id}

    def inside(group: h5py.Group, path: str) -> Iterator[Entry]:
        yield _group_entry(file, group, path)
        for member in group:
            child = _join(path, member)
            held = isinstance(group.get(member, getlink=True), h5py.HardLink)
            try:
                found = _resolved(file, child, "")
            except _Refused as refused:
                yield Entry(child, "other", problem=refused.why)
                continue
            if isinstance(found, h5py.Dataset):
                yield _dataset_entry(found, child)
            elif isinstance(found, h5py.Group):
                if held and found.id not in seen:
                    seen.add(found.id)
                    yield from inside(found, child)
                else:
                    yield _group_entry(file, found, child)

    yield from inside(file["/"], "/")


def likely(found: list[Entry], name: str) -> Entry:
    """The entry that looks most like the data meant: a group with two columns
    of one length, else a table of records, an image, a group of several
    columns, or a column."""
    usable = [e for e in found if not e.problem]
    for wanted in (
        lambda e: e.kind == "group" and len(set(e.lengths)) < len(e.lengths),
        lambda e: e.kind == "table",
        lambda e: e.kind == "image",
        lambda e: e.kind == "group" and len(e.columns) > 1,
        lambda e: e.kind == "column",
    ):
        for entry in usable:
            if wanted(entry):
                return entry
    if usable:
        return usable[0]
    raise DataError(f"{name} holds no numbers that can be plotted")


def _checked(entry: Entry, name: str) -> Entry:
    if entry.problem:
        raise DataError(f"cannot plot {name}, {entry.path}: {entry.problem}")
    return entry


def _chosen(file: h5py.File, path: str, name: str) -> Entry:
    try:
        found = _resolved(file, path, name)
    except _Refused:
        raise
    except DataError as exc:
        known = ", ".join(e.path for e in _walk(file) if not e.problem)
        raise DataError(f"{exc}; it has {known}") from exc
    if isinstance(found, h5py.Group):
        return _checked(_group_entry(file, found, path), name)
    if isinstance(found, h5py.Dataset):
        return _checked(_dataset_entry(found, path), name)
    raise DataError(f"cannot plot {name}, {path}: it is not data")


def _unit(dataset: h5py.Dataset) -> str:
    """The "units" (or "unit") attribute as text; "" if there is none."""
    for key in ("units", "unit"):
        try:
            value = dataset.attrs.get(key)
        except (OSError, TypeError, ValueError):
            continue  # a kind of attribute h5py cannot read
        if isinstance(value, np.ndarray) and value.size == 1:
            value = value.item()
        if isinstance(value, bytes):
            try:
                value = value.decode()
            except UnicodeDecodeError:
                value = value.decode("latin-1")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
