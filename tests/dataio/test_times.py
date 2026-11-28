"""Reading dates and times (decision 0082)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import h5py
import numpy as np
import pytest

from figscribe.io import DataError, load_data
from figscribe.io.csvfile import csv_source
from figscribe.io.hdf5file import entries, hdf5_source
from figscribe.io.numpyfile import numpy_source
from figscribe.io.sheetfile import sheet_source
from figscribe.model import ArrayRef, ColumnRef, Project
from figscribe.times import parse_times
from tests.hdf5files import write_h5
from tests.sheetfiles import write_ods, write_xlsx


def _times(*texts: str) -> np.ndarray:
    return np.array(texts, dtype="datetime64[us]")


NOON = _times("2026-11-01T12:00", "2026-11-01T12:10", "2026-11-01T12:20")


def _read(source, tmp_path: Path, column) -> np.ndarray:
    data = load_data(Project(sources=[source]), tmp_path)
    return data(ColumnRef(source=source.id, column=column))


def _same(values: np.ndarray, expected: np.ndarray) -> None:
    assert values.dtype == np.dtype("datetime64[us]")
    np.testing.assert_array_equal(values, expected)


@pytest.mark.parametrize(
    "text",
    [
        "2026-11-01",
        "2026-11-01 12:00",
        "2026-11-01T12:00:30",
        "2026-11-01 12:00:30.25",
        "2026-11-01T12:00Z",
        "2026-11-01 12:00:00+01:00",
        "2026-11-01 12:00:00-0530",
        " 2026-11-01 12:00 ",
    ],
)
def test_what_is_a_time(text: str) -> None:
    assert parse_times([text]) is not None


@pytest.mark.parametrize(
    "text",
    [
        "2026",
        "2026-11",
        "20261101",
        "01.11.2026",
        "12:00",
        "2026-13-01",
        "2026-02-30",
        "2026-11-01+01:00",  # a zone says nothing about a day
        "now",
        "1.5",
        "NaT",
    ],
)
def test_what_is_not_a_time(text: str) -> None:
    assert parse_times([text]) is None


def test_times_are_read_as_written() -> None:
    values = parse_times(["2026-11-01T12:00+01:00", "", "2026-11-01 12:00Z"])
    _same(values, _times("2026-11-01T12:00", "NaT", "2026-11-01T12:00"))
    assert parse_times(["", ""]) is None  # nothing says these are times


def _csv(tmp_path: Path, text: str, **options):
    path = tmp_path / "log.csv"
    path.write_text(text, encoding="utf-8")
    return csv_source(path, tmp_path, **options)


def test_a_csv_with_a_date_column(tmp_path: Path) -> None:
    source = _csv(
        tmp_path,
        "time,T\n2026-11-01 12:00,20.1\n2026-11-01 12:10,20.3\n2026-11-01 12:20,20.2\n",
    )
    assert (source.time_columns, source.trim_times) == ([0], False)
    _same(_read(source, tmp_path, "time"), NOON)
    np.testing.assert_array_equal(_read(source, tmp_path, "T"), [20.1, 20.3, 20.2])
    assert source.row_count == 3


def test_a_csv_with_zones_blanks_and_gaps(tmp_path: Path) -> None:
    source = _csv(
        tmp_path,
        "T;time;end\n20,1;2026-11-01T12:00+01:00 ;2026-11-02\n20,3;;2026-11-03\n",
        delimiter=";",
        decimal=",",
    )
    assert (source.time_columns, source.trim_times) == ([1, 2], True)
    _same(_read(source, tmp_path, "time"), _times("2026-11-01T12:00", "NaT"))
    _same(_read(source, tmp_path, "end"), _times("2026-11-02", "2026-11-03"))
    np.testing.assert_array_equal(_read(source, tmp_path, "T"), [20.1, 20.3])


def test_a_csv_without_names_and_split_on_blanks(tmp_path: Path) -> None:
    source = _csv(
        tmp_path,
        "2026-11-01T12:00  1\n2026-11-01T12:10  2\n",
        delimiter=None,
        header_row=None,
    )
    assert source.time_columns == [0]
    _same(_read(source, tmp_path, 0), NOON[:2])
    np.testing.assert_array_equal(_read(source, tmp_path, 1), [1.0, 2.0])


def test_times_that_come_late_in_a_column(tmp_path: Path) -> None:
    rows = "".join(f",{i}\n" for i in range(3)) + "2026-11-01,3\n"
    source = _csv(tmp_path, "time,n\n" + rows)
    assert source.time_columns == [0]


def test_a_column_that_is_not_all_times_stays_unreadable(tmp_path: Path) -> None:
    source = _csv(tmp_path, "time,T\n2026-11-01,1\nlater,2\n")
    assert source.time_columns == []
    with pytest.raises(DataError, match="later|2026-11-01"):
        _read(source, tmp_path, "time")


def test_a_csv_with_times_is_no_table(tmp_path: Path) -> None:
    source = _csv(tmp_path, "time,T\n2026-11-01,1\n")
    data = load_data(Project(sources=[source]), tmp_path)
    with pytest.raises(DataError, match="holds dates"):
        data(ArrayRef(source=source.id))


@pytest.mark.parametrize("name", ["t.npy", "t.npz"])
def test_numpy_datetime64(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    stamps = np.array(["2026-11-01T12:00", "NaT"], dtype="datetime64[s]")
    if name.endswith("npz"):
        np.savez(path, t=stamps)
    else:
        np.save(path, stamps)
    source = numpy_source(path, tmp_path)
    assert source.time_columns == [0]
    # Before decision 0082 these were read as large integers.
    _same(_read(source, tmp_path, 0), _times("2026-11-01T12:00", "NaT"))


def test_numpy_numbers_have_no_time_columns(tmp_path: Path) -> None:
    np.save(tmp_path / "n.npy", np.arange(6.0).reshape(3, 2))
    assert numpy_source(tmp_path / "n.npy", tmp_path).time_columns == []


def test_numpy_two_columns_of_datetime64(tmp_path: Path) -> None:
    np.save(tmp_path / "m.npy", np.stack([NOON, NOON], axis=1))
    source = numpy_source(tmp_path / "m.npy", tmp_path)
    assert source.time_columns == [0, 1]
    _same(_read(source, tmp_path, 1), NOON)


@pytest.mark.parametrize("write", [write_xlsx, write_ods])
def test_date_cells_of_a_spreadsheet(tmp_path: Path, write) -> None:
    path = tmp_path / ("log.ods" if write is write_ods else "log.xlsx")
    stamps = [datetime(2026, 11, 1, 12, minute) for minute in (0, 10, 20)]
    write(
        path,
        {
            "s": [["time", "text", "T"]]
            + [[stamp, str(stamp), i] for i, stamp in enumerate(stamps)]
        },
    )
    source = sheet_source(path, tmp_path)
    assert source.time_columns == [0, 1]
    _same(_read(source, tmp_path, "time"), NOON)
    _same(_read(source, tmp_path, "text"), NOON)
    np.testing.assert_array_equal(_read(source, tmp_path, "T"), [0, 1, 2])


def test_the_other_cells_of_times(monkeypatch, tmp_path: Path) -> None:
    from figscribe.io import sheetfile

    cells = [
        ["day", "took", "clock"],
        [date(2026, 11, 1), timedelta(minutes=2), time(12, 0)],
        ["", timedelta(hours=1), time(13, 0)],
    ]
    write_xlsx(tmp_path / "x.xlsx", {"s": [["a"]]})
    monkeypatch.setattr(sheetfile, "read_cells", lambda *a: cells)
    monkeypatch.setattr(sheetfile, "sheet_names", lambda *a: ["s"])
    source = sheetfile.sheet_source(tmp_path / "x.xlsx", tmp_path)
    assert source.time_columns == [0]
    _same(_read(source, tmp_path, "day"), _times("2026-11-01", "NaT"))
    for column in ("took", "clock"):
        with pytest.raises(DataError, match="without a date"):
            _read(source, tmp_path, column)


@pytest.mark.parametrize("holds", ["group", "table", "column"])
def test_hdf5_text_and_timestamps(tmp_path: Path, holds: str) -> None:
    iso = np.array(
        [b"2026-11-01T12:00+01:00", b"2026-11-01 12:10", b"2026-11-01 12:20"]
    )
    path = tmp_path / "log.h5"
    if holds == "table":
        records = np.zeros(3, dtype=[("time", iso.dtype), ("T", "f8")])
        records["time"] = iso
        write_h5(path, {"run": records})
    elif holds == "column":
        write_h5(path, {"time": iso})
    else:
        stamps = NOON.astype(h5py.opaque_dtype(NOON.dtype))
        write_h5(path, {"run/time": iso, "run/stamp": stamps, "run/T": np.arange(3.0)})
    source = hdf5_source(path, tmp_path)
    names = source.columns
    expected = {"group": ["T", "stamp", "time"], "table": ["time", "T"]}
    assert names == expected.get(holds, ["time"])
    assert source.time_columns == [
        i for i, name in enumerate(names) if name in ("time", "stamp")
    ]
    for name in names:
        values = _read(source, tmp_path, name)
        if name == "T":
            assert values.dtype == float
        else:
            _same(values, NOON)


def test_hdf5_text_that_is_not_times_stays_left_out(tmp_path: Path) -> None:
    path = write_h5(
        tmp_path / "t.h5", {"run/name": np.array([b"a", b"b"]), "run/T": [1.0, 2]}
    )
    run = next(e for e in entries(path.read_bytes(), "t.h5") if e.path == "/run")
    assert run.columns == ["T"] and run.left_out == {"name": "it holds text"}


def test_a_newer_version_of_a_file_with_times(tmp_path: Path) -> None:
    from figscribe.io.refresh import reread

    path = tmp_path / "log.csv"
    source = _csv(tmp_path, "time,T\n2026-11-01 12:00,1\n")
    path.write_text("time,T\n2026-11-01 12:00Z,1\n2026-11-01 12:10Z,2\n")
    new = reread(source, tmp_path)
    assert (new.time_columns, new.trim_times, new.row_count) == ([0], True, 2)
    path.write_text("time,T\nlater,1\n")
    with pytest.raises(DataError, match="later"):
        reread(source, tmp_path)
