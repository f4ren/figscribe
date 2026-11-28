"""Excel and LibreOffice Calc files (decision 0079).

A source is one sheet: a row of column names, perhaps rows to skip below it,
then the rows of data; wholly empty rows are left out. A column is made into
numbers when it is used, so notes elsewhere do no harm; a column of dates is
read as times (decision 0082). The script the code generator writes reads the
file the same way.

Read with python-calamine, which takes what the file stores: a formula's
result is the one saved with it, and a formula error reads as an empty cell.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path

import numpy as np
from python_calamine import CalamineWorkbook, SheetTypeEnum, SheetVisibleEnum

from figscribe.io.errors import CellError, DataError
from figscribe.io.files import sha256_of, stored_path
from figscribe.model import SheetSource
from figscribe.times import parse_times

FORMATS = {".xlsx": "xlsx", ".xlsm": "xlsx", ".xls": "xls", ".ods": "ods"}
"""The file name endings that are read as sheets, with the format of each."""


def sheet_source(
    path: str | Path,
    base_dir: str | Path,
    *,
    sheet: str | None = None,
    header_row: int | None = 0,
    skip_rows: int = 0,
    decimal: str = ".",
) -> SheetSource:
    """Describe a sheet of a spreadsheet file for the model: hash the file and
    read the column names. `sheet` None means the first one; rows are counted
    from 0, the spreadsheet's row 1."""
    path = Path(path)
    raw = path.read_bytes()
    if sheet is None:
        sheet = sheet_names(raw, path.name)[0]
    columns, first_column, rows = _table(
        read_cells(raw, path.name, sheet), header_row, skip_rows, path.name, sheet
    )
    return SheetSource(
        format=FORMATS.get(path.suffix.lower(), "xlsx"),
        path=stored_path(path, base_dir),
        sha256=sha256_of(path),
        sheet=sheet,
        header_row=header_row,
        skip_rows=skip_rows,
        decimal=decimal,
        first_column=first_column,
        time_columns=[
            i
            for i in range(len(columns))
            if _times(_cells(rows, first_column + i)) is not None
        ],
        columns=columns,
        row_count=len(rows),
    )


def sheet_names(raw: bytes, name: str) -> list[str]:
    """The sheets of cells of a spreadsheet file: those one sees in their
    order, then the hidden ones. Chart sheets hold no cells."""
    sheets = _opened(
        raw,
        name,
        lambda book: [(s.name, s.typ, s.visible) for s in book.sheets_metadata],
    )
    cells = [(n, v) for n, kind, v in sheets if kind == SheetTypeEnum.WorkSheet]
    cells.sort(key=lambda sheet: sheet[1] != SheetVisibleEnum.Visible)  # stable
    names = [n for n, _ in cells]
    if not names:
        raise DataError(f"{name} has no sheets")
    return names


def read_cells(raw: bytes, name: str, sheet: str) -> list[list[object]]:
    """Every row of a sheet from its row 1 and column A, as the library gives
    the cells: numbers, text, bool, dates and times, "" for empty."""
    names = sheet_names(raw, name)
    if sheet not in names:
        known = ", ".join(repr(n) for n in names)
        raise DataError(f"{name} has no sheet {sheet!r}; it has {known}")
    return _opened(
        raw,
        name,
        lambda book: book.get_sheet_by_name(sheet).to_python(skip_empty_area=False),
    )


@dataclass(frozen=True)
class SheetTable:
    """The rows of data of one sheet, made into numbers a column at a time."""

    name: str
    """The file's name, for messages."""
    sheet: str
    rows: list[tuple[int, list[object]]]
    """(row number as the spreadsheet counts it, all its cells)."""
    first_column: int
    width: int
    decimal: str
    time_columns: tuple[int, ...] = ()

    def column(self, index: int) -> np.ndarray:
        """The column `index` of the table (from 0): floats, NaN for empty; or
        times, NaT for empty."""
        at = self.first_column + index
        if index in self.time_columns:
            times = _times(_cells([row for _, row in self.rows], at))
            if times is None:
                raise CellError(
                    f"cannot read {self.name}: sheet {self.sheet!r}, column "
                    f"{column_letters(at)} is not all dates"
                )
            return times
        values = np.empty(len(self.rows))
        for i, (number, cells) in enumerate(self.rows):
            cell = cells[at] if at < len(cells) else ""
            try:
                values[i] = _number(cell, self.decimal)
            except ValueError as exc:
                raise CellError(
                    f"cannot read {self.name}: sheet {self.sheet!r}, cell "
                    f"{column_letters(at)}{number}{exc}"
                ) from None
        return values

    def array(self) -> np.ndarray:
        """Every column, as 2-D data for images and color meshes."""
        if self.time_columns:
            raise CellError(
                f"{self.name}, sheet {self.sheet!r}, holds dates, so it is no table "
                "of numbers"
            )
        return np.column_stack([self.column(i) for i in range(self.width)])


def read_sheet(source: SheetSource, raw: bytes, name: str) -> SheetTable:
    """The source's table, read from the file contents `raw`."""
    cells = read_cells(raw, name, source.sheet)
    first = _first_data_row(source.header_row, source.skip_rows)
    rows = [
        (number, row)
        for number, row in enumerate(cells[first:], first + 1)
        if not _blank_row(row)
    ]
    if not rows:
        raise DataError(f"{name}, sheet {source.sheet!r}, has no rows of data")
    right = max(_last_filled(row) for _, row in rows) + 1
    width = max(len(source.columns), right - source.first_column, 1)
    return SheetTable(
        name,
        source.sheet,
        rows,
        source.first_column,
        width,
        source.decimal,
        tuple(source.time_columns),
    )


def column_letters(index: int) -> str:
    """The spreadsheet's name of the column `index` (from 0): A, ..., Z, AA."""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


def cell_text(cell: object) -> str:
    """A cell as the preview and the column names show it."""
    if isinstance(cell, bool):
        return "TRUE" if cell else "FALSE"
    if isinstance(cell, float) and math.isfinite(cell) and cell == int(cell):
        return str(int(cell))
    return " ".join(str(cell).split())


def _number(cell: object, decimal: str) -> float:
    """The cell's number, NaN for an empty one; a ValueError that finishes a
    sentence starting with the cell's name."""
    if isinstance(cell, str):
        text = cell.strip()
        if not text:
            return math.nan
        try:
            return float(text.replace(decimal, "."))
        except ValueError:
            hint = (
                "; if the file writes numbers with a decimal comma, set the "
                "decimal mark"
                if decimal == "." and "," in text
                else ""
            )
            raise ValueError(f": {text!r} is not a number{hint}") from None
    if isinstance(cell, bool):
        raise ValueError(" holds TRUE or FALSE, not a number")
    if isinstance(cell, time | timedelta):
        raise ValueError(
            " holds a time of day or a duration without a date, which figscribe "
            "cannot plot; put the date in the same cell, or use numbers"
        )
    if isinstance(cell, date):
        raise ValueError(" holds a date, in a column that is not all dates")
    return float(cell)


def _cells(rows: list[list[object]], at: int) -> list[object]:
    return [row[at] if at < len(row) else "" for row in rows]


def _times(cells: list[object]) -> np.ndarray | None:
    """The cells as times, if every filled one is a date or ISO text of one."""
    texts = []
    for cell in cells:
        if isinstance(cell, date):  # and so a date with a time of day
            cell = cell.isoformat()
        if not isinstance(cell, str):
            return None
        texts.append(cell)
    return parse_times(texts)


def _blank(cell: object) -> bool:
    return isinstance(cell, str) and not cell.strip()


def _blank_row(row: list[object]) -> bool:
    return all(_blank(cell) for cell in row)


def _last_filled(row: list[object]) -> int:
    return next((i for i in range(len(row) - 1, -1, -1) if not _blank(row[i])), -1)


def _first_data_row(header_row: int | None, skip_rows: int) -> int:
    return (0 if header_row is None else header_row + 1) + skip_rows


def _table(
    cells: list[list[object]],
    header_row: int | None,
    skip_rows: int,
    name: str,
    sheet: str,
) -> tuple[list[str], int, list[list[object]]]:
    """(column names, first column, rows of data) of a sheet read this way."""
    where = f"{name}, sheet {sheet!r},"
    if header_row is not None and header_row >= len(cells):
        raise DataError(f"{where} has no row {header_row + 1} for the column names")
    first = _first_data_row(header_row, skip_rows)
    rows = [row for row in cells[first:] if not _blank_row(row)]
    if not rows:
        raise DataError(f"{where} has no rows of data")
    header = [] if header_row is None else cells[header_row]
    taken = [row for row in [header, *rows] if not _blank_row(row)]
    first_column = min(
        next(i for i, cell in enumerate(row) if not _blank(cell)) for row in taken
    )
    width = max(_last_filled(row) for row in taken) + 1
    columns = []
    for at in range(first_column, width):
        cell = header[at] if at < len(header) else ""
        title = cell_text(cell) or f"column {column_letters(at)}"
        if title in columns:  # side by side blocks repeat their names
            title = f"{title} (column {column_letters(at)})"
        columns.append(title)
    return columns, first_column, rows


def _opened(raw: bytes, name: str, read):
    """`read(workbook)` of the file contents, with any failure as a DataError:
    the library raises errors of its own, and its Rust part may panic, which
    is not an Exception."""
    try:
        return read(CalamineWorkbook.from_filelike(io.BytesIO(raw)))
    except (KeyboardInterrupt, SystemExit, MemoryError):
        raise
    except BaseException as exc:
        raise DataError(f"cannot read {name}: {exc}") from exc
