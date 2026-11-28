"""Errors raised while reading data files."""


class DataError(Exception):
    """A data source cannot be read as described."""


class DataChangedError(DataError):
    """A data file no longer matches the hash recorded in the project."""


class CellError(DataError):
    """What is plotted cannot be made into numbers: a cell of a spreadsheet
    without one, or HDF5 datasets of different lengths taken as one table."""
