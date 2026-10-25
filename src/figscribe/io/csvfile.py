"""CSV and other delimited text files.

Parsing goes through np.loadtxt with the options stored in the CsvSource, so
the code generator can emit the very same call and the script reads the file
exactly as the renderer did.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import get_args

import numpy as np

from figscribe.io.errors import DataError
from figscribe.io.files import sha256_of, stored_path
from figscribe.model import CsvSource
from figscribe.model.data import CsvEncoding


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
    return CsvSource(
        path=stored_path(path, base_dir),
        sha256=sha256_of(path),
        delimiter=delimiter,
        decimal=decimal,
        header_row=header_row,
        skip_rows=skip_rows,
        comment=comment,
        encoding=encoding,
        columns=columns,
        row_count=_data_rows(text.splitlines()[first:], comment),
    )


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
    # loadtxt would split "1,5" into two fields and read wrong numbers silently.
    if source.decimal == source.delimiter:
        raise DataError(
            f"cannot read {name}: decimal separator {source.decimal!r} "
            "is also the delimiter"
        )
    first_data_line = (
        0 if source.header_row is None else source.header_row + 1
    ) + source.skip_rows
    converters = None
    if source.decimal != ".":
        decimal = source.decimal
        converters = lambda field: float(field.replace(decimal, "."))  # noqa: E731
    try:
        table = np.loadtxt(
            io.StringIO(decode(raw, source.encoding, name)),
            delimiter=source.delimiter,
            skiprows=first_data_line,
            comments=source.comment,
            converters=converters,
            ndmin=2,
        )
    except ValueError as exc:
        raise DataError(f"cannot read {name}: {exc}") from exc
    return table


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
