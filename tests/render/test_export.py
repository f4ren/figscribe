"""Export at exact physical sizes, with byte-stable vector output."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from PIL import Image

from figscribe.model import Axes, Figure, LinePlot
from figscribe.render import export, export_bytes

MM_PER_INCH = 25.4


@pytest.fixture
def figure(ref) -> Figure:
    return Figure(
        width_mm=85.0,
        height_mm=60.0,
        dpi=300.0,
        axes=[Axes(artists=[LinePlot(x=ref("t"), y=ref("U"))])],
    )


def test_png_has_the_size_in_pixels(figure, data, tmp_path: Path) -> None:
    path = tmp_path / "f.png"
    export(figure, data, path)
    # Matplotlib truncates to whole pixels: 85 mm at 300 dpi is 1003.94 px.
    expected = tuple(
        math.floor(mm / MM_PER_INCH * figure.dpi)
        for mm in (figure.width_mm, figure.height_mm)
    )
    assert Image.open(path).size == expected


def test_pdf_has_the_size_in_points(figure, data, tmp_path: Path) -> None:
    path = tmp_path / "f.pdf"
    export(figure, data, path)
    box = re.search(rb"/MediaBox \[ *0 0 ([\d.]+) ([\d.]+) *\]", path.read_bytes())
    assert box is not None
    width_pt, height_pt = (float(v) for v in box.groups())
    assert width_pt == pytest.approx(85.0 / MM_PER_INCH * 72)
    assert height_pt == pytest.approx(60.0 / MM_PER_INCH * 72)


def test_svg_has_the_size_in_points(figure, data, tmp_path: Path) -> None:
    path = tmp_path / "f.svg"
    export(figure, data, path)
    match = re.search(
        r'<svg[^>]*width="([\d.]+)pt" height="([\d.]+)pt"', path.read_text()
    )
    assert match is not None
    assert float(match[1]) == pytest.approx(85.0 / MM_PER_INCH * 72, abs=1e-5)


@pytest.mark.parametrize("suffix", [".pdf", ".svg"])
def test_vector_output_is_byte_stable(suffix, figure, data, tmp_path: Path) -> None:
    # No timestamps or random ids, so an unchanged figure gives an unchanged file.
    a, b = tmp_path / f"a{suffix}", tmp_path / f"b{suffix}"
    export(figure, data, a)
    export(figure, data, b)
    assert a.read_bytes() == b.read_bytes()


def test_unknown_format_is_refused(figure, data, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.jpg"):
        export(figure, data, tmp_path / "f.jpg")


@pytest.mark.parametrize("suffix", [".png", ".pdf", ".svg"])
def test_the_bytes_are_the_file_that_export_writes(
    suffix, figure, data, tmp_path: Path
) -> None:
    # The clipboard gets the figure as exported, not another rendering of it.
    path = tmp_path / f"f{suffix}"
    export(figure, data, path)
    assert export_bytes(figure, data, suffix) == path.read_bytes()


def test_bytes_of_an_unknown_format_are_refused(figure, data) -> None:
    with pytest.raises(ValueError, match=r"\.jpg"):
        export_bytes(figure, data, ".jpg")
