"""CSV and other delimited text files.

Parsing goes through np.loadtxt with the options stored in the CsvSource, so
the code generator can emit the very same call and the script reads the file
exactly as the renderer did.
"""

from __future__ import annotations

import csv
import io
import warnings
from pathlib import Path
from typing import get_args

import numpy as np

from figscribe.io.errors import CellError, DataError
from figscribe.io.files import sha256_of, stored_path
from figscribe.model import CsvSource
from figscribe.model.data import CsvEncoding
from figscribe.times import is_time, needs_trimming, parse_times


def csv_source(
    path: str | Path,
    base_dir: str | Path,
    *,
    delimiter: str | None = ",",
    decimal: str = ".",
    header_row: int | None = 0,
    skip_rows: int = 0,
    comment: str | None = "#",
    encoding: CsvEncoding = "utf-8-sig",
) -> CsvSource:
    """Describe a CSV file for the model: hash it and read its column names.

    The path is stored relative to `base_dir`, the project file's directory,
    when the file lies below it, so that a project folder can be moved as a
    whole.
    """
    if decimal == delimiter:
        raise DataError(f"decimal separator {decimal!r} is also the delimiter")
    path = Path(path)
    text = decode(path.read_bytes(), encoding, str(path))
    columns = [] if header_row is None else _header(text, delimiter, header_row, path)
    first = (0 if header_row is None else header_row + 1) + skip_rows
    time_columns, trim = _find_times(text, delimiter, first, comment)
    return CsvSource(
        path=stored_path(path, base_dir),
        sha256=sha256_of(path),
        delimiter=delimiter,
        decimal=decimal,
        header_row=header_row,
        skip_rows=skip_rows,
        comment=comment,
        encoding=encoding,
        time_columns=time_columns,
        trim_times=trim,
        columns=columns,
        row_count=_data_rows(text.splitlines()[first:], comment),
    )


def _find_times(
    text: str, delimiter: str | None, first: int, comment: str | None
) -> tuple[list[int], bool]:
    """(the columns that are dates and times, whether they need trimming)."""

    def fields(**more) -> np.ndarray:
        return np.loadtxt(
            io.StringIO(text),
            delimiter=delimiter,
            skiprows=first,
            comments=comment,
            dtype=str,
            ndmin=2,
            **more,
        )

    found, trim = [], False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # "no data": said when reading
            start = fields(max_rows=100)
            if not start.size:
                return [], False
            # A column whose start is blank may yet hold times further down.
            for index, column in enumerate(start.T):
                filled = [field for field in column if field.strip()]
                if filled and not is_time(filled[0]):
                    continue
                values = fields(usecols=index)[:, 0]
                if parse_times(values) is not None:
                    found.append(index)
                    trim = trim or needs_trimming(values)
    except ValueError:  # rows of different widths; reading the file says so
        return [], False
    return found, trim


class CsvTable:
    """The columns of a CSV file with dates and times, which cannot all be
    read as one table of numbers."""

    def __init__(self, source: CsvSource, raw: bytes, name: str):
        self.source = source
        self._name = Path(name).name
        self._text = decode(raw, source.encoding, name)
        self._table: np.ndarray | None = None
        _check_marks(source, self._name)
        self.width = self._load(dtype=str, max_rows=1).shape[1]
        if not self.width:
            raise DataError(f"{self._name} has no rows of data")

    def column(self, index: int) -> np.ndarray:
        """The column `index` (from 0): times, or floats."""
        numbers = self._all_numbers()  # which also checks every row's width
        if index in self.source.time_columns:
            values = parse_times(self._load(dtype=str, usecols=index)[:, 0])
            if values is None:
                raise DataError(
                    f"cannot read {self._name}: column {index + 1} is not all times"
                )
            return values
        return numbers[:, index].copy()

    def _all_numbers(self) -> np.ndarray:
        """Every column read in one go, those of dates as zeros: rows of
        different widths are refused, which reading some columns would not."""
        if self._table is None:
            skip = dict.fromkeys(self.source.time_columns, _nothing)
            self._table = _numbers(self.source, self._text, self._name, skip=skip)
        return self._table

    def check(self) -> None:
        """A DataError if any column cannot be read."""
        for index in range(self.width):
            self.column(index)

    def array(self) -> np.ndarray:
        raise CellError(f"{self._name} holds dates, so it is no table of numbers")

    def _load(self, **more) -> np.ndarray:
        source = self.source
        try:
            return np.loadtxt(
                io.StringIO(self._text),
                delimiter=source.delimiter,
                skiprows=_first_data_line(source),
                comments=source.comment,
                ndmin=2,
                **more,
            )
        except ValueError as exc:
            raise DataError(f"cannot read {self._name}: {exc}") from exc


def detect_encoding(raw: bytes) -> CsvEncoding:
    """The first encoding that reads all of `raw`; Latin-1 reads anything."""
    *tried, last = get_args(CsvEncoding)
    for encoding in tried:
        try:
            raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return last


def decode(raw: bytes, encoding: str, name: str) -> str:
    """The file contents `raw` as text; `name` only appears in the error."""
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise DataError(
            f"{name} is not {encoding} text (byte {exc.start + 1}); choose the "
            "file's text encoding, often cp1252 for files from Windows programs"
        ) from exc


def read_csv(source: CsvSource, raw: bytes, name: str) -> np.ndarray:
    """Parse the file contents `raw` into a 2-D array, one column per field.

    `name` only appears in error messages.
    """
    _check_marks(source, name)
    table = _numbers(source, decode(raw, source.encoding, name), name)
    if table.size == 0:  # NumPy then gives one column of nothing
        raise DataError(f"{Path(name).name} has no rows of data")
    return table


def _first_data_line(source: CsvSource) -> int:
    first = 0 if source.header_row is None else source.header_row + 1
    return first + source.skip_rows


def _check_marks(source: CsvSource, name: str) -> None:
    # loadtxt would split "1,5" into two fields and read wrong numbers silently.
    if source.decimal == source.delimiter:
        raise DataError(
            f"cannot read {name}: decimal separator {source.decimal!r} "
            "is also the delimiter"
        )


def _nothing(field: str) -> float:
    return 0.0


def _numbers(
    source: CsvSource, text: str, name: str, skip: dict | None = None
) -> np.ndarray:
    """The table of numbers; `skip` gives the converter of columns that are
    not numbers."""
    converters = None
    if source.decimal != ".":
        decimal = source.decimal
        converters = lambda field: float(field.replace(decimal, "."))  # noqa: E731
    if skip:
        width = len(
            np.loadtxt(
                io.StringIO(text),
                delimiter=source.delimiter,
                skiprows=_first_data_line(source),
                comments=source.comment,
                dtype=str,
                max_rows=1,
                ndmin=2,
            )[0]
        )
        usual = converters
        converters = dict.fromkeys(range(width), usual) if usual else {}
        converters.update(skip)
    try:
        return np.loadtxt(
            io.StringIO(text),
            delimiter=source.delimiter,
            skiprows=_first_data_line(source),
            comments=source.comment,
            converters=converters,
            ndmin=2,
        )
    except ValueError as exc:
        raise DataError(f"cannot read {name}: {exc}") from exc


def _data_rows(lines: list[str], comment: str | None) -> int:
    """The lines np.loadtxt reads as data: all but blank and comment-only ones."""
    if comment:
        lines = [line.split(comment, 1)[0] for line in lines]
    return sum(1 for line in lines if line.strip())


def _header(text: str, delimiter: str | None, header_row: int, path: Path) -> list[str]:
    lines = text.splitlines()
    if header_row >= len(lines):
        raise DataError(f"{path} has no line {header_row} to take column names from")
    line = lines[header_row]
    if delimiter is None:
        fields = line.split()
    else:
        fields = next(csv.reader([line], delimiter=delimiter))
    return [f.strip() for f in fields]
