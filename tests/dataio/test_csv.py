"""Reading CSV sources: hashing, header handling and the data provider."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from figscribe.io import (
    DataChangedError,
    DataError,
    csv_source,
    load_data,
    sha256_of,
)
from figscribe.model import ColumnRef, CsvSource, Project


def write(path: Path, text: str) -> Path:
    # Bytes, not write_text: on Windows that would turn \n into \r\n.
    path.write_bytes(text.encode("utf-8"))
    return path


def test_sha256_of_file(tmp_path: Path) -> None:
    path = write(tmp_path / "a.csv", "x\n1\n")
    assert sha256_of(path) == hashlib.sha256(b"x\n1\n").hexdigest()


def test_csv_source_records_hash_and_columns(tmp_path: Path) -> None:
    write(tmp_path / "scan.csv", "t,U,dU\n0,1,0.1\n1,2,0.1\n")
    source = csv_source(tmp_path / "scan.csv", base_dir=tmp_path)
    assert source.path == "scan.csv"
    assert source.sha256 == sha256_of(tmp_path / "scan.csv")
    assert source.columns == ["t", "U", "dU"]


def test_csv_source_outside_base_dir_keeps_an_absolute_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write(data_dir / "scan.csv", "t\n0\n")
    source = csv_source(data_dir / "scan.csv", base_dir=tmp_path / "project")
    assert Path(source.path).is_absolute()


def _load(tmp_path: Path, source: CsvSource, column: str | int) -> np.ndarray:
    data = load_data(Project(sources=[source]), base_dir=tmp_path)
    return data(ColumnRef(source=source.id, column=column))


def test_columns_by_name_and_index(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U\n0,1.5\n1,2.5\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    assert list(_load(tmp_path, source, "U")) == [1.5, 2.5]
    assert list(_load(tmp_path, source, 0)) == [0.0, 1.0]


def test_metadata_lines_above_the_header_and_a_units_line_below(tmp_path: Path) -> None:
    write(
        tmp_path / "s.csv",
        "instrument: X\ndate: 2026-10-12\nt,U\ns,V\n0,1\n1,2\n",
    )
    source = csv_source(
        tmp_path / "s.csv", base_dir=tmp_path, header_row=2, skip_rows=1
    )
    assert source.columns == ["t", "U"]
    assert list(_load(tmp_path, source, "U")) == [1.0, 2.0]


def test_no_header_means_index_columns(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "junk\n0,1\n1,2\n")
    source = csv_source(
        tmp_path / "s.csv", base_dir=tmp_path, header_row=None, skip_rows=1
    )
    assert source.columns == []
    assert list(_load(tmp_path, source, 1)) == [1.0, 2.0]


def test_whitespace_delimiter_and_decimal_comma(tmp_path: Path) -> None:
    write(tmp_path / "s.dat", "t   U\n0   1,5\n1\t2,5\n")
    source = csv_source(
        tmp_path / "s.dat", base_dir=tmp_path, delimiter=None, decimal=","
    )
    assert source.columns == ["t", "U"]
    assert list(_load(tmp_path, source, "U")) == [1.5, 2.5]


def test_semicolon_delimiter_with_quoted_header(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", '"t";"U"\n0;1\n')
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path, delimiter=";")
    assert source.columns == ["t", "U"]


def test_comment_lines_in_the_data_are_skipped(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U\n0,1\n# pause\n1,2\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    assert list(_load(tmp_path, source, "U")) == [1.0, 2.0]


def test_byte_order_mark_from_excel_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "s.csv").write_bytes("﻿t,U\n0,1\n".encode())
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    assert source.columns == ["t", "U"]


WINDOWS_TEXT = "t,I (µA)\n0,1\n1,2\n".encode("cp1252")
"""As lab software on Windows writes it: µ is one byte, not valid UTF-8."""


def test_a_windows_file_read_as_utf8_names_the_encoding(tmp_path: Path) -> None:
    (tmp_path / "s.csv").write_bytes(WINDOWS_TEXT)
    with pytest.raises(DataError, match=r"s\.csv.*encoding"):
        csv_source(tmp_path / "s.csv", base_dir=tmp_path)


def test_a_windows_file_reads_with_its_encoding(tmp_path: Path) -> None:
    (tmp_path / "s.csv").write_bytes(WINDOWS_TEXT)
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path, encoding="cp1252")
    assert source.encoding == "cp1252"
    assert source.columns == ["t", "I (µA)"]
    assert list(_load(tmp_path, source, "I (µA)")) == [1.0, 2.0]

    source.encoding = "utf-8-sig"  # changed afterwards, e.g. by hand
    with pytest.raises(DataError, match="encoding"):
        _load(tmp_path, source, "t")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("t\n".encode("utf-8-sig"), "utf-8-sig"),
        ("µ\n".encode(), "utf-8-sig"),
        ("µ\n".encode("cp1252"), "cp1252"),
        (b"\x81\xb5\n", "latin-1"),  # 0x81 is not a cp1252 character
    ],
)
def test_the_encoding_is_detected(raw: bytes, expected: str) -> None:
    from figscribe.io.csvfile import detect_encoding

    assert detect_encoding(raw) == expected


def test_single_row_still_gives_columns(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U\n0,1\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    assert list(_load(tmp_path, source, "U")) == [1.0]


def test_changed_file_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path / "s.csv", "t,U\n0,1\n")
    source = csv_source(path, base_dir=tmp_path)
    write(path, "t,U\n0,2\n")
    with pytest.raises(DataChangedError, match="s.csv"):
        _load(tmp_path, source, "U")


def test_unknown_column_is_reported_with_the_known_ones(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U\n0,1\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    with pytest.raises(DataError, match=r"'V'.*'t', 'U'"):
        _load(tmp_path, source, "V")


def test_column_index_out_of_range(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U\n0,1\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    with pytest.raises(DataError, match="2 columns"):
        _load(tmp_path, source, 5)


def test_header_wider_than_the_data_is_reported(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U,dU\n0,1\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    with pytest.raises(DataError, match="'dU' is out of range.*2 columns"):
        _load(tmp_path, source, "dU")


def test_decimal_comma_with_comma_delimiter_is_refused(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U\n0,1,5\n")
    with pytest.raises(DataError, match="also the delimiter"):
        csv_source(tmp_path / "s.csv", base_dir=tmp_path, decimal=",")

    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    source.decimal = ","
    with pytest.raises(DataError, match="also the delimiter"):
        _load(tmp_path, source, "U")


def test_non_numeric_value_names_the_file(tmp_path: Path) -> None:
    write(tmp_path / "s.csv", "t,U\n0,abc\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    with pytest.raises(DataError, match="s.csv"):
        _load(tmp_path, source, "U")


def test_unknown_source_is_reported(tmp_path: Path) -> None:
    data = load_data(Project(), base_dir=tmp_path)
    with pytest.raises(DataError, match="unknown data source"):
        data(ColumnRef(source="nope", column=0))


def test_each_file_is_read_once(tmp_path: Path, monkeypatch) -> None:
    write(tmp_path / "s.csv", "t,U\n0,1\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    data = load_data(Project(sources=[source]), base_dir=tmp_path)
    data(ColumnRef(source=source.id, column="t"))

    (tmp_path / "s.csv").unlink()
    assert list(data(ColumnRef(source=source.id, column="U"))) == [1.0]


def test_a_file_without_rows_of_data_says_so(tmp_path: Path) -> None:
    """Not "column 'y' is out of range: has 1 columns", which NumPy's empty
    result made it say."""
    write(tmp_path / "s.csv", "x,y,dy\n")
    source = csv_source(tmp_path / "s.csv", base_dir=tmp_path)
    with pytest.raises(DataError, match="s.csv has no rows of data"):
        _load(tmp_path, source, "y")
