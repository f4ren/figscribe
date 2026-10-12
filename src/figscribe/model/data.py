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


class CsvSource(Identified):
    format: Literal["csv"] = "csv"
    path: str = Field(min_length=1)
    sha256: Sha256
    delimiter: str = ","
    decimal: str = "."
    header_row: int | None = Field(0, ge=0)
    skip_rows: int = Field(0, ge=0)
    comment: str | None = "#"
    columns: list[str] = Field(default_factory=list)
    """Column names discovered on import, cached for the GUI."""


class Hdf5Source(Identified):
    format: Literal["hdf5"] = "hdf5"
    path: str = Field(min_length=1)
    sha256: Sha256
    dataset: str = Field(min_length=1)
    """Path of the dataset inside the file, e.g. "/run3/voltage"."""
    columns: list[str] = Field(default_factory=list)


class NumpySource(Identified):
    format: Literal["npy", "npz"] = "npy"
    path: str = Field(min_length=1)
    sha256: Sha256
    array: str | None = None
    """Array name inside an .npz archive; None for a plain .npy file."""
    columns: list[str] = Field(default_factory=list)


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
