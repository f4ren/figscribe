"""Excel and LibreOffice Calc files as data (decision 0079)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from figscribe.io import DataError, load_data
from figscribe.io.sheetfile import sheet_names, sheet_source
from figscribe.model import ArrayRef, ColumnRef, Project, SheetSource, dumps, loads
from tests.sheetfiles import Error, Formula, write_ods, write_xlsx

nan = float("nan")

ROWS = [
    ["A measurement of something"],
    [],
    [None, "t", "U", None, "twice", "note"],
    [None, "s", "V"],
    [None, 1, 2.5, None, Formula("C5*2", 5.0), "ok"],
    [None, 2, None, None, Formula("C6*2", None), datetime(2026, 3, 4, 12, 30)],
    [],
    [None, 3, "3.5", None, Formula("C8*2", 7.0), True],
]

WRITERS = {"xlsx": write_xlsx, "ods": write_ods}


@pytest.fixture(params=WRITERS)
def book(tmp_path: Path, request) -> Path:
    path = tmp_path / f"scan.{request.param}"
    WRITERS[request.param](path, {"run 1": ROWS, "other": [["x"], [1]]})
    return path


def _load(tmp_path: Path, source: SheetSource, column: str | int) -> np.ndarray:
    data = load_data(Project(sources=[source]), tmp_path)
    return data(ColumnRef(source=source.id, column=column))


def test_the_names_of_the_sheets_in_their_order(book: Path) -> None:
    assert sheet_names(book.read_bytes(), book.name) == ["run 1", "other"]


def test_a_source_records_the_sheet_and_its_table(book: Path) -> None:
    source = sheet_source(book, book.parent, header_row=2, skip_rows=1)
    assert source.format == book.suffix[1:]
    assert (source.path, source.sheet) == (book.name, "run 1")
    assert source.first_column == 1  # nothing in column A below the names
    assert source.columns == ["t", "U", "column D", "twice", "note"]
    assert source.row_count == 3  # the empty row is left out


def test_columns_are_numbers_with_gaps_and_stored_results(book: Path) -> None:
    source = sheet_source(book, book.parent, header_row=2, skip_rows=1)
    np.testing.assert_array_equal(_load(book.parent, source, "t"), [1, 2, 3])
    np.testing.assert_array_equal(_load(book.parent, source, "U"), [2.5, nan, 3.5])
    np.testing.assert_array_equal(_load(book.parent, source, "twice"), [5, nan, 7])


def test_a_cell_that_is_no_number_is_named_when_its_column_is_used(book: Path) -> None:
    source = sheet_source(book, book.parent, header_row=2, skip_rows=1)
    with pytest.raises(DataError, match=r"sheet 'run 1', cell F5: 'ok' is not"):
        _load(book.parent, source, "note")


@pytest.mark.parametrize(
    ("value", "why"),
    [
        (datetime(2026, 3, 4), "F2 holds a date or time"),
        (True, "F2 holds TRUE or FALSE"),
        ("n/a", "F2: 'n/a' is not a number"),
    ],
)
@pytest.mark.parametrize("kind", WRITERS)
def test_what_is_refused(tmp_path: Path, kind: str, value, why: str) -> None:
    path = tmp_path / f"a.{kind}"
    WRITERS[kind](path, {"s": [["a", "b", "c", "d", "e", "f"], [1, 1, 1, 1, 1, value]]})
    source = sheet_source(path, tmp_path)
    with pytest.raises(DataError, match=why):
        _load(tmp_path, source, "f")


def test_a_formula_error_reads_as_an_empty_cell(tmp_path: Path) -> None:
    write_xlsx(tmp_path / "a.xlsx", {"s": [["a", "b"], [1, Error()], [2, 4]]})
    source = sheet_source(tmp_path / "a.xlsx", tmp_path)
    np.testing.assert_array_equal(_load(tmp_path, source, "b"), [nan, 4])


@pytest.mark.parametrize("kind", WRITERS)
def test_numbers_written_as_text_follow_the_decimal_mark(tmp_path: Path, kind) -> None:
    path = tmp_path / f"a.{kind}"
    WRITERS[kind](path, {"s": [["a"], ["1,5"], ["  2 "], [3.25], ["   "]]})
    source = sheet_source(path, tmp_path, decimal=",")
    np.testing.assert_array_equal(_load(tmp_path, source, "a"), [1.5, 2, 3.25])
    with pytest.raises(DataError, match="A2: '1,5' is not a number.*decimal comma"):
        _load(tmp_path, sheet_source(path, tmp_path), "a")


@pytest.mark.parametrize("kind", WRITERS)
def test_numbers_as_names_and_no_names(tmp_path: Path, kind: str) -> None:
    path = tmp_path / f"a.{kind}"
    WRITERS[kind](path, {"s": [[300, 77.5, "U\n(V)"], [1, 2, 3]]})
    assert sheet_source(path, tmp_path).columns == ["300", "77.5", "U (V)"]
    bare = sheet_source(path, tmp_path, header_row=None)
    assert bare.columns == [] and bare.row_count == 2
    np.testing.assert_array_equal(_load(tmp_path, bare, 1), [77.5, 2])


def test_the_whole_table_is_an_array(tmp_path: Path) -> None:
    write_ods(tmp_path / "a.ods", {"s": [["a", "b"], [1, 2], [3, None]]})
    source = sheet_source(tmp_path / "a.ods", tmp_path)
    data = load_data(Project(sources=[source]), tmp_path)
    np.testing.assert_array_equal(data(ArrayRef(source=source.id)), [[1, 2], [3, nan]])


def test_the_old_excel_format(tmp_path: Path) -> None:
    path = tmp_path / "old.xls"
    path.write_bytes((Path(__file__).parent / "old.xls").read_bytes())
    source = sheet_source(path, tmp_path, header_row=1, skip_rows=1)
    assert (source.format, source.first_column) == ("xls", 1)
    np.testing.assert_array_equal(_load(tmp_path, source, "t"), [1, 2, 3])
    with pytest.raises(DataError, match="cell C6 holds TRUE or FALSE"):
        _load(tmp_path, source, "U")


@pytest.mark.parametrize(
    ("options", "why"),
    [
        ({"sheet": "nope"}, "no sheet 'nope'; it has 'run 1', 'other'"),
        ({"header_row": 99}, "no row 100"),
        ({"header_row": 7}, "no rows of data"),
    ],
)
def test_options_that_do_not_fit_the_file(book: Path, options, why: str) -> None:
    with pytest.raises(DataError, match=why):
        sheet_source(book, book.parent, **options)


@pytest.mark.parametrize("raw", [b"", b"t,U\n1,2\n", b"PK\x03\x04 broken"])
def test_a_file_that_is_no_spreadsheet(tmp_path: Path, raw: bytes) -> None:
    (tmp_path / "a.xlsx").write_bytes(raw)
    with pytest.raises(DataError, match="cannot read a.xlsx"):
        sheet_source(tmp_path / "a.xlsx", tmp_path)


def test_a_sheet_source_survives_saving(book: Path) -> None:
    project = Project(sources=[sheet_source(book, book.parent, header_row=2)])
    assert loads(dumps(project)).sources == project.sources
