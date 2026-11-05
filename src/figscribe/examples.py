"""The examples that ship with figscribe (decision 0053).

They live in `examples/` of a checkout and, installed, in the package; each has
a folder with its data, its project and a thumbnail, and `index.json` names
them. `examples/make.py` writes all of it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import figscribe


def examples_root() -> Path:
    """The folder of the examples: inside the package when installed, in the
    repository when run from a checkout."""
    packaged = resources.files("figscribe") / "examples"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(figscribe.__file__).parents[2] / "examples"


@dataclass(frozen=True)
class Example:
    folder: str
    """The folder's name, which is also the example's name."""
    project: str
    """The project file in it."""
    title: str
    detail: str
    """One line on what the example shows."""

    @property
    def path(self) -> Path:
        return examples_root() / self.folder

    @property
    def project_file(self) -> Path:
        return self.path / self.project

    @property
    def thumbnail(self) -> Path:
        return self.path / "thumbnail.png"


def gallery() -> list[Example]:
    """Every example, in the order of `index.json`."""
    index = json.loads((examples_root() / "index.json").read_text(encoding="utf-8"))
    return [Example(**entry) for entry in index["examples"]]


def bundled_example() -> Path:
    """The folder of the first example, the Gaussian scan."""
    return examples_root() / "gaussian-scan"
