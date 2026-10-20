"""The example project that ships with figscribe."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import figscribe


def bundled_example() -> Path:
    """The example project's folder: inside the package when installed, in
    the repository when run from a checkout."""
    packaged = resources.files("figscribe") / "examples" / "gaussian-scan"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(figscribe.__file__).parents[2] / "examples" / "gaussian-scan"
