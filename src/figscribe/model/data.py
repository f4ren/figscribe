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


class CsvSource(Identified):
    format: Literal["csv"] = "csv"
    path: str = Field(min_length=1)
    sha256: Sha256
    delimiter: str | None = ","
    """None splits on any run of whitespace, as in many .dat files."""
    decimal: str = Field(".", min_length=1, max_length=1)
    header_row: int | None = Field(0, ge=0)
    """Line number (from 0) of the column names; lines above it are skipped.
    None means no header, and columns are addressed by index."""
    skip_rows: int = Field(0, ge=0)
    """Lines skipped between the header and the data, e.g. a line of units.
    Without a header, lines skipped at the top of the file."""
    comment: str | None = "#"
    """Lines starting with this are skipped; counted lines above include them."""
    encoding: CsvEncoding = "utf-8-sig"
    columns: list[str] = Field(default_factory=list)
    """Column names discovered on import, cached for the GUI."""
    row_count: int | None = Field(None, ge=0)
    """Rows of data when the file was imported, to tell what changed; None in
    projects from before it was recorded."""


class Hdf5Source(Identified):
    format: Literal["hdf5"] = "hdf5"
    path: str = Field(min_length=1)
    sha256: Sha256
    dataset: str = Field(min_length=1)
    """Path of the dataset inside the file, e.g. "/run3/voltage"."""
    columns: list[str] = Field(default_factory=list)
    row_count: int | None = Field(None, ge=0)
    """Rows of data when the file was imported, to tell what changed; None in
    projects from before it was recorded."""


class NumpySource(Identified):
    format: Literal["npy", "npz"] = "npy"
    path: str = Field(min_length=1)
    sha256: Sha256
    array: str | None = None
    """Array name inside an .npz archive; None for a plain .npy file."""
    columns: list[str] = Field(default_factory=list)
    row_count: int | None = Field(None, ge=0)
    """Rows of data when the file was imported, to tell what changed; None in
    projects from before it was recorded."""


DataSource = Annotated[
    CsvSource | Hdf5Source | NumpySource,
    Field(discriminator="format"),
]


class ColumnRef(StrictModel):
    """One 1-D column within a data source."""

    source: str = Field(min_length=1)
    """DataSource.id."""
    column: str | int


class ArrayRef(StrictModel):
    """A 2-D array within a data source, for images and color meshes."""

    source: str = Field(min_length=1)
    key: str | None = None
    """Dataset or array name; None means the source's default array."""
