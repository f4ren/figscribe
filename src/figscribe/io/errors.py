"""Errors raised while reading data files."""


class DataError(Exception):
    """A data source cannot be read as described."""


class DataChangedError(DataError):
    """A data file no longer matches the hash recorded in the project."""
