"""Excel and LibreOffice Calc files as data (decision 0079)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from figscribe.commands import History
from figscribe.datafile import columns_to_choose, sheets_to_choose, use_another_file
from figscribe.io import DataError, load_data
from figscribe.io.refresh import read_differently, reading_options, use_new_version
from figscribe.io.sheetfile import sheet_names, sheet_source
from figscribe.model import (
    ArrayRef,
    Axes,
    ColumnRef,
    Figure,
    LinePlot,
    Project,
    SheetSource,
    dumps,
    loads,
)
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
    assert bare.columns == ["column A", "column B", "column C"]
    assert bare.row_count == 2
    np.testing.assert_array_equal(_load(tmp_path, bare, "column B"), [77.5, 2])
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


# --- changed and other files -------------------------------------------------

SCAN = [["t", "U", "note"], [1, 2.0, "start"], [2, 4.0, None], [3, 6.0, "end"]]


def _plotted(tmp_path: Path, kind: str = "ods", rows=SCAN, sheets=None) -> Project:
    """A plot of U over t of a sheet with a column of notes."""
    path = tmp_path / f"scan.{kind}"
    WRITERS[kind](path, sheets or {"run 1": rows})
    source = sheet_source(path, tmp_path)
    refs = {c: ColumnRef(source=source.id, column=c) for c in ("t", "U")}
    line = LinePlot(x=refs["t"], y=refs["U"])
    return Project(sources=[source], figures=[Figure(axes=[Axes(artists=[line])])])


def _y(project: Project, folder: Path) -> np.ndarray:
    return load_data(project, folder)(project.figures[0].axes[0].artists[0].y)


@pytest.mark.parametrize("kind", WRITERS)
def test_a_new_version_with_notes_is_taken(tmp_path: Path, kind: str) -> None:
    project = _plotted(tmp_path, kind)
    WRITERS[kind](
        tmp_path / f"scan.{kind}",
        {"run 1": [["when", *SCAN[0]], *(["noon", *r] for r in SCAN[1:]), ["", 4, 8]]},
    )
    source = project.sources[0]
    use_new_version(project, source.id, tmp_path).apply(project)
    new = project.sources[0]
    assert (new.columns, new.row_count) == (["when", "t", "U", "note"], 4)
    np.testing.assert_array_equal(_y(project, tmp_path), [2, 4, 6, 8])


def test_a_new_version_whose_plotted_column_has_text_is_refused(tmp_path) -> None:
    project = _plotted(tmp_path)
    write_ods(tmp_path / "scan.ods", {"run 1": [SCAN[0], [1, "oops"]]})
    with pytest.raises(DataError, match="cell B2: 'oops' is not a number"):
        use_new_version(project, project.sources[0].id, tmp_path)


def test_where_the_table_starts_goes_with_a_new_version(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    write_ods(tmp_path / "scan.ods", {"run 1": [[None, *row] for row in SCAN]})
    use_new_version(project, project.sources[0].id, tmp_path).apply(project)
    assert project.sources[0].first_column == 1
    np.testing.assert_array_equal(_y(project, tmp_path), [2, 4, 6])


def test_another_file_of_another_format_with_one_sheet(tmp_path: Path) -> None:
    project = _plotted(tmp_path, "ods")
    write_xlsx(tmp_path / "next.xlsx", {"2026-11-27": [["t", "U"], [1, 10], [2, 20]]})
    source = project.sources[0]
    path = tmp_path / "next.xlsx"
    assert sheets_to_choose(project, source.id, tmp_path, path) == {}
    assert columns_to_choose(project, source.id, tmp_path, path) == []
    use_another_file(project, source.id, tmp_path, path).command.apply(project)
    new = project.sources[0]
    assert (new.format, new.sheet, new.path) == ("xlsx", "2026-11-27", "next.xlsx")
    np.testing.assert_array_equal(_y(project, tmp_path), [10, 20])


def test_which_sheet_is_asked_where_it_cannot_be_told(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    write_ods(
        tmp_path / "two.ods",
        {"a": [["t", "U"], [1, 10]], "b": [["t", "U"], [1, 30]]},
    )
    source = project.sources[0]
    path = tmp_path / "two.ods"
    assert sheets_to_choose(project, source.id, tmp_path, path) == {"run 1": ["a", "b"]}
    with pytest.raises(DataError, match="no sheet 'run 1'"):
        use_another_file(project, source.id, tmp_path, path)
    chosen = {"run 1": "b"}
    assert columns_to_choose(project, source.id, tmp_path, path, chosen) == []
    use_another_file(project, source.id, tmp_path, path, sheets=chosen).command.apply(
        project
    )
    assert project.sources[0].sheet == "b"
    np.testing.assert_array_equal(_y(project, tmp_path), [30])


def test_a_spreadsheet_does_not_take_the_place_of_another_kind(tmp_path) -> None:
    project = _plotted(tmp_path)
    (tmp_path / "scan.csv").write_text("t,U\n1,2\n", encoding="utf-8")
    with pytest.raises(DataError, match="scan.csv is not a spreadsheet"):
        use_another_file(
            project, project.sources[0].id, tmp_path, tmp_path / "scan.csv"
        )


def test_the_sheet_and_the_rows_are_how_a_file_is_read(tmp_path: Path) -> None:
    project = _plotted(
        tmp_path,
        sheets={
            "run 1": SCAN,
            "run 2": [["t", "U"], ["s", "V"], [1, 100]],
        },
    )
    source = project.sources[0]
    assert reading_options(source) == ("sheet", "header_row", "skip_rows", "decimal")
    history = History(project)
    history.push(read_differently(project, source.id, "sheet", "run 2", tmp_path))
    with pytest.raises(DataError, match="'V' is not a number"):
        _y(project, tmp_path)
    history.push(read_differently(project, source.id, "skip_rows", 1, tmp_path))
    np.testing.assert_array_equal(_y(project, tmp_path), [100])
    assert project.sources[0].row_count == 1
    with pytest.raises(DataError, match="no sheet 'nope'"):
        read_differently(project, source.id, "sheet", "nope", tmp_path)


def test_a_way_of_reading_that_makes_no_numbers_is_refused(tmp_path: Path) -> None:
    rows = [["t", "U"], [1, "1,5"], [2, "3,5"]]
    write_ods(tmp_path / "a.ods", {"s": rows})
    source = sheet_source(tmp_path / "a.ods", tmp_path, decimal=",")
    a, b = (ColumnRef(source=source.id, column=c) for c in ("t", "U"))
    figure = Figure(axes=[Axes(artists=[LinePlot(x=a, y=b)])])
    project = Project(sources=[source], figures=[figure])
    with pytest.raises(DataError, match="'1,5' is not a number"):
        read_differently(project, source.id, "decimal", ".", tmp_path)
