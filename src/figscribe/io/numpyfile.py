"""NumPy files: .npy holds one array, .npz several by name.

Read with np.load and never with pickles, so a data file cannot run code; the
code generator emits the same call.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from figscribe.io.errors import DataError
from figscribe.io.files import sha256_of, stored_path
from figscribe.model import NumpySource


def numpy_source(
    path: str | Path, base_dir: str | Path, array: str | None = None
) -> NumpySource:
    """Describe a .npy or .npz file for the model; an .npz file's array is
    `array`, or its first one."""
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix.lower() == ".npz":
        names = array_names(raw, path.name)
        if array is None:
            array = names[0]
        elif array not in names:
            raise DataError(f"{path.name} has no array {array!r}")
        kind = "npz"
    else:
        kind, array = "npy", None
    source = NumpySource(
        format=kind,
        path=stored_path(path, base_dir),
        sha256=sha256_of(path),
        array=array,
    )
    read_numpy(source, raw, path.name)  # refuse what cannot be plotted now
    return source


def array_names(raw: bytes, name: str) -> list[str]:
    """The arrays in an .npz file, in their stored order."""
    try:
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            names = list(archive.files)
    except (OSError, ValueError) as exc:
        raise DataError(f"cannot read {name}: {exc}") from exc
    if not names:
        raise DataError(f"{name} holds no arrays")
    return names


def read_numpy(
    source: NumpySource, raw: bytes, name: str, key: str | None = None
) -> np.ndarray:
    """The source's array (an .npz file's `key`, or the source's own) as
    floats, at most two-dimensional."""
    try:
        loaded = np.load(io.BytesIO(raw), allow_pickle=False)
        if isinstance(loaded, np.lib.npyio.NpzFile):
            with loaded:
                wanted = key or source.array
                if wanted not in loaded.files:
                    raise DataError(f"{name} has no array {wanted!r}")
                array = loaded[wanted]
        else:
            array = loaded
        array = np.asarray(array, dtype=float)
    except (OSError, ValueError, TypeError) as exc:
        raise DataError(f"cannot read {name}: {exc}") from exc
    if array.ndim not in (1, 2):
        raise DataError(
            f"{name} holds a {array.ndim}-D array; figscribe plots 1-D and 2-D"
        )
    return array
