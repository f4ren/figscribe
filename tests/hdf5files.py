"""HDF5 files for the tests, written where a test needs them."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np


def write_h5(path: Path, datasets: dict[str, object]) -> Path:
    """A file with the arrays `datasets` under their paths, such as
    "run1/t"; a value may also be a link (`h5py.SoftLink`, ...)."""
    with h5py.File(path, "w") as file:
        for name, value in datasets.items():
            file[name] = value
    return path


def write_scan(path: Path) -> Path:
    """A file as a lab program writes it: one group per run, with units, a
    value that is no column, and a table of records."""
    t = np.linspace(0.0, 4.0, 9)
    with h5py.File(path, "w") as file:
        run = file.create_group("run1")
        run["t"] = t
        run["t"].attrs["units"] = "s"
        run["U"] = (3 * t + 1).astype("f4")
        run["U"].attrs["units"] = np.bytes_("µV".encode())
        run["counts"] = np.arange(9, dtype="u2")
        run["gain"] = 20.0
        run["comment"] = "warm"
        table = np.zeros(4, dtype=[("f", "f8"), ("name", "S4"), ("n", "i4")])
        table["f"] = [10.0, 20.0, 30.0, 40.0]
        table["name"] = [b"a", b"b", b"c", b"d"]
        table["n"] = [4, 3, 2, 1]
        file["table"] = table
        file["image"] = np.arange(12.0).reshape(3, 4)
    return path
