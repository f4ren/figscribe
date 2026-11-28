"""Data sources and references into them.

Measurements never live in the model. A source records where a file is, how to
read it and what it hashed to; artists point into it by reference. That keeps
the model small and makes the data hash in the generated code trivial.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from figscribe.model.base import Identified, StrictModel

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

CsvEncoding = Literal["utf-8-sig", "cp1252", "latin-1"]
"""Text encodings of CSV files, in the order they are tried on import:
UTF-8 (with or without the byte order mark Excel puts in front), what Windows
programs write, and Latin-1, which reads any bytes."""


Times = list[Annotated[int, Field(ge=0)]]
"""Numbers of columns, from 0."""


class CsvSource(Identified):
    format: Literal["csv"] = "csv"
    path: str = Field(min_length=1)
    """Where the file is: relative to the project's folder when it lies below it."""
    sha256: Sha256
    """SHA-256 of the file when it was imported; a changed file is refused."""
    delimiter: str | None = Field(",", min_length=1, max_length=1)
    """One character; None splits on any run of whitespace, as in many .dat
    files."""
    decimal: str = Field(".", min_length=1, max_length=1)
    """The decimal mark of the numbers: "." or ","."""
    header_row: int | None = Field(0, ge=0)
    """Line number (from 0) of the column names; lines above it are skipped.
    None means no header, and columns are addressed by index."""
    skip_rows: int = Field(0, ge=0)
    """Lines skipped between the header and the data, e.g. a line of units.
    Without a header, lines skipped at the top of the file."""
    comment: str | None = "#"
    """Lines starting with this are skipped; counted lines above include them."""
    encoding: CsvEncoding = "utf-8-sig"
    """How the file's text is stored: UTF-8, or cp1252 and Latin-1 as older Windows
    programs write it."""
    time_columns: Times = Field(default_factory=list)
    """The columns (from 0) that are dates and times, found on import."""
    trim_times: bool = False
    """Time fields carry blanks or a time zone, which are taken off as they are
    read."""
    columns: list[str] = Field(default_factory=list)
    """Column names discovered on import, cached for the GUI."""
    row_count: int | None = Field(None, ge=0)
    """Rows of data when the file was imported, to tell what changed; None in
    projects from before it was recorded."""


class Hdf5Source(Identified):
    """One group or dataset of an HDF5 file (decision 0081)."""

    format: Literal["hdf5"] = "hdf5"
    path: str = Field(min_length=1)
    """Where the file is: relative to the project's folder when it lies below it."""
    sha256: Sha256
    """SHA-256 of the file when it was imported; a changed file is refused."""
    dataset: str = Field(min_length=1)
    """Path inside the file of the data: a group, whose one-dimensional
    datasets are the columns, such as "/run3", or one dataset, such as
    "/run3/voltage"; "/" for what the file holds at the top."""
    holds: Literal["group", "table", "column", "image"] = "group"
    """What is at `dataset`: a group of datasets, a table of records, a dataset
    of one dimension (a column) or of two (an image). Recorded on import, so
    that the script can be written without the file."""
    columns: list[str] = Field(default_factory=list)
    """Column names discovered on import: the group's datasets, the fields of a
    table of records, or the dataset's own name. None for a two-dimensional
    dataset."""
    time_columns: Times = Field(default_factory=list)
    """The columns (from 0) that are dates and times, found on import."""
    row_count: int | None = Field(None, ge=0)
    """Rows of data when the file was imported, to tell what changed; None in
    projects from before it was recorded."""


class NumpySource(Identified):
    format: Literal["npy", "npz"] = "npy"
    """"npy" for a single array, "npz" for an archive of several."""
    path: str = Field(min_length=1)
    """Where the file is: relative to the project's folder when it lies below it."""
    sha256: Sha256
    """SHA-256 of the file when it was imported; a changed file is refused."""
    array: str | None = None
    """Array name inside an .npz archive; None for a plain .npy file."""
    columns: list[str] = Field(default_factory=list)
    """Column names, if known; a NumPy array has none of its own."""
    time_columns: Times = Field(default_factory=list)
    """The columns (from 0) that are dates and times, found on import."""
    row_count: int | None = Field(None, ge=0)
    """Rows of data when the file was imported, to tell what changed; None in
    projects from before it was recorded."""


class SheetSource(Identified):
    """One sheet of an Excel or LibreOffice Calc file (decision 0079)."""

    format: Literal["xlsx", "xls", "ods"] = "xlsx"
    """Excel (.xlsx, .xlsm, or the old .xls) or LibreOffice Calc (.ods)."""
    path: str = Field(min_length=1)
    """Where the file is: relative to the project's folder when it lies below it."""
    sha256: Sha256
    """SHA-256 of the file when it was imported; a changed file is refused."""
    sheet: str = Field(min_length=1)
    """The sheet's name."""
    header_row: int | None = Field(0, ge=0)
    """Row (from 0, the spreadsheet's row 1) of the column names; rows above it
    are skipped. None means no names, and columns are addressed by index."""
    skip_rows: int = Field(0, ge=0)
    """Rows skipped between the names and the data, e.g. a row of units."""
    decimal: str = Field(".", min_length=1, max_length=1)
    """The decimal mark of numbers stored as text."""
    first_column: int = Field(0, ge=0)
    """The sheet's column (from 0, column A) the table starts at."""
    columns: list[str] = Field(default_factory=list)
    """Column names discovered on import, cached for the GUI."""
    time_columns: Times = Field(default_factory=list)
    """The columns (from 0) that are dates and times, found on import."""
    row_count: int | None = Field(None, ge=0)
    """Rows of data when the file was imported, to tell what changed."""


FILE_SOURCES = (CsvSource, Hdf5Source, NumpySource, SheetSource)
"""The kinds of source that are read from a file."""

BY_COLUMN_SOURCES = (Hdf5Source, SheetSource)
"""The kinds of source whose columns are read one at a time: such a file may
hold things beside what is plotted that are no numbers."""

DataSource = Annotated[
    CsvSource | Hdf5Source | NumpySource | SheetSource,
    Field(discriminator="format"),
]


class ColumnRef(StrictModel):
    """One 1-D column within a data source."""

    source: str = Field(min_length=1)
    """DataSource.id."""
    column: str | int
    """Column name, or its number from 0 for files without names."""


class ArrayRef(StrictModel):
    """A 2-D array within a data source, for images and color meshes."""

    source: str = Field(min_length=1)
    """DataSource.id."""
    key: str | None = None
    """Dataset or array name; None means the source's default array."""
