"""The examples that ship with figscribe (decision 0053): each opens without a
problem, is listed, is small, and is what `examples/make.py` writes."""

from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from figscribe.examples import examples_root, gallery
from figscribe.io import load_data
from figscribe.model import FitCurve, dumps, loads, validate_references
from figscribe.render import export

ROOT = Path(__file__).parents[1] / "examples"
NAMES = [example.folder for example in gallery()]
MAX_BYTES = 1_000_000
"""The whole folder stays under this: the examples are in every install."""


def test_there_are_examples() -> None:
    assert len(NAMES) >= 12
    assert examples_root().resolve() == ROOT.resolve()


def test_every_folder_is_listed_and_every_listing_exists() -> None:
    folders = {p.name for p in ROOT.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert folders == set(NAMES)
    for example in gallery():
        assert example.project_file.is_file(), example.folder
        assert example.title and example.detail


def test_the_examples_are_small() -> None:
    total = sum(f.stat().st_size for f in ROOT.rglob("*") if f.is_file())
    assert total < MAX_BYTES, f"{total} bytes"


@pytest.mark.parametrize("name", NAMES)
def test_an_example_has_a_thumbnail_of_the_size_the_start_page_expects(
    name: str,
) -> None:
    path = ROOT / name / "thumbnail.png"
    assert path.is_file()
    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == (520, 340)
    assert path.stat().st_size < 80_000


@pytest.mark.parametrize("name", NAMES)
def test_an_example_opens_without_a_problem(name: str, tmp_path: Path) -> None:
    example = next(e for e in gallery() if e.folder == name)
    project = loads(example.project_file.read_text(encoding="utf-8"))
    data = load_data(project, example.path)
    assert validate_references(project, data) == []
    for figure in project.figures:
        export(figure, data, tmp_path / f"{figure.id}.png")
    fits = [
        artist
        for figure in project.figures
        for axes in figure.axes
        for artist in axes.artists
        if isinstance(artist, FitCurve)
    ]
    for fit in fits:
        assert fit.result is not None and fit.result.converged, name


@pytest.mark.parametrize("name", NAMES)
def test_the_data_is_where_the_project_says_and_is_text_or_an_archive(
    name: str,
) -> None:
    example = next(e for e in gallery() if e.folder == name)
    project = loads(example.project_file.read_text(encoding="utf-8"))
    for source in project.sources:
        assert not Path(source.path).is_absolute()
        assert (example.path / source.path).is_file()
    for csv in example.path.glob("*.csv"):
        assert b"\r" not in csv.read_bytes(), "the hash must not depend on the platform"


def _generator():
    spec = importlib.util.spec_from_file_location("examples_make", ROOT / "make.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _without_results(text: str) -> tuple[dict, list[dict]]:
    """A project as data with the results of its fits taken out and listed."""
    project = loads(text)
    results = []
    for figure in project.figures:
        for axes in figure.axes:
            for artist in axes.artists:
                if isinstance(artist, FitCurve):
                    results.append(artist.result.model_dump())
                    artist.result = None
    return json.loads(dumps(project)), results


@pytest.mark.slow
def test_make_writes_what_is_committed(tmp_path: Path) -> None:
    """Nobody edits an example by hand and lets it drift: running the generator
    gives the same files, the fits' results to within what SciPy's versions
    differ by."""
    make = _generator()
    make.main(root=tmp_path)
    assert (tmp_path / "index.json").read_text() == (ROOT / "index.json").read_text()
    for name in NAMES:
        written, kept = tmp_path / name, ROOT / name
        project_file = make.EXAMPLES[name][0]
        if make.EXAMPLES[name][3] is None:  # written by hand: a thumbnail only
            assert (written / "thumbnail.png").is_file()
            continue
        for data in kept.iterdir():
            if data.suffix == ".csv":
                assert (written / data.name).read_bytes() == data.read_bytes(), (
                    name,
                    data.name,
                )
            if data.suffix == ".npz":
                a, b = np.load(written / data.name), np.load(data)
                assert sorted(a.files) == sorted(b.files)
                for key in a.files:
                    assert np.allclose(a[key], b[key], rtol=1e-9, atol=0)
        new, new_results = _without_results((written / project_file).read_text())
        old, old_results = _without_results((kept / project_file).read_text())
        assert new == old, name
        for a, b in zip(new_results, old_results, strict=True):
            for key, value in a["parameters"].items():
                assert value == pytest.approx(b["parameters"][key], rel=1e-5, abs=1e-12)


def test_a_png_is_a_png() -> None:
    # The thumbnails are read by the start page through Qt; a plain check that
    # the signature is right keeps a broken file from reaching it.
    for name in NAMES:
        head = (ROOT / name / "thumbnail.png").read_bytes()[:8]
        assert struct.unpack("8B", head) == (137, 80, 78, 71, 13, 10, 26, 10)
