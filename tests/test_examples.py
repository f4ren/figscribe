"""Every example project loads, is sound, and renders from its own files.

These are also the projects the codegen equivalence test (M2) will run on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from figscribe.io import load_data
from figscribe.model import loads, validate_references
from figscribe.render import export

EXAMPLES = sorted((Path(__file__).parents[1] / "examples").glob("*/*.figscribe"))


def test_there_are_examples() -> None:
    assert EXAMPLES


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_example_renders(path: Path, tmp_path: Path) -> None:
    project = loads(path.read_text(encoding="utf-8"))
    assert validate_references(project) == []

    data = load_data(project, base_dir=path.parent)
    for i, figure in enumerate(project.figures):
        out = tmp_path / f"{i}.png"
        export(figure, data, out)
        assert Image.open(out).size[0] > 0
