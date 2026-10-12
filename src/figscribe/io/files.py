"""File helpers shared by all source formats."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def sha256_of(path: str | Path) -> str:
    """Return the SHA-256 hex digest of the file at `path`."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stored_path(path: Path, base_dir: str | Path) -> str:
    """The path as written into the project: relative to `base_dir` with
    forward slashes when the file lies below it, absolute otherwise."""
    path = Path(os.path.abspath(path))
    try:
        return path.relative_to(os.path.abspath(base_dir)).as_posix()
    except ValueError:
        return str(path)


def resolve_path(stored: str, base_dir: str | Path) -> Path:
    """Inverse of `stored_path`."""
    path = Path(stored)
    return path if path.is_absolute() else Path(base_dir) / path
