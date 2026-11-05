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
    # Matplotlib writes an SVG file as text, so on Windows its lines end in
    # CRLF; the bytes in memory end in LF. The picture is the same.
    written = path.read_bytes()
    if suffix == ".svg":
        written = written.replace(b"\r\n", b"\n")
    assert export_bytes(figure, data, suffix) == written


def test_bytes_of_an_unknown_format_are_refused(figure, data) -> None:
    with pytest.raises(ValueError, match=r"\.jpg"):
        export_bytes(figure, data, ".jpg")


# --- TIFF, EPS and a transparent background (roadmap R3, decision 0065) -----------


def test_tiff_has_the_size_and_resolution_and_is_compressed(
    figure, data, tmp_path: Path
) -> None:
    path = tmp_path / "f.tif"
    export(figure, data, path)
    image = Image.open(path)
    expected = tuple(
        math.floor(mm / MM_PER_INCH * figure.dpi)
        for mm in (figure.width_mm, figure.height_mm)
    )
    assert image.size == expected
    assert image.info["compression"] == "tiff_lzw"  # journals ask for it
    assert image.info["dpi"][0] == pytest.approx(figure.dpi, abs=1)


def test_the_tiff_suffixes_are_the_same_format(figure, data, tmp_path: Path) -> None:
    export(figure, data, tmp_path / "a.tif")
    export(figure, data, tmp_path / "b.tiff")
    assert (tmp_path / "a.tif").read_bytes() == (tmp_path / "b.tiff").read_bytes()


def test_eps_is_an_encapsulated_postscript_of_the_size(
    figure, data, tmp_path: Path
) -> None:
    path = tmp_path / "f.eps"
    export(figure, data, path)
    text = path.read_bytes().decode("latin-1")
    assert text.startswith("%!PS-Adobe-3.0 EPSF-3.0")
    box = re.search(r"%%BoundingBox: 0 0 (\d+) (\d+)", text)
    assert box is not None
    assert int(box.group(1)) == pytest.approx(85.0 / MM_PER_INCH * 72, abs=1)
    assert int(box.group(2)) == pytest.approx(60.0 / MM_PER_INCH * 72, abs=1)


@pytest.mark.parametrize("suffix", [".tif", ".eps"])
def test_the_new_formats_are_byte_stable_too(
    figure, data, tmp_path: Path, suffix: str
) -> None:
    # The same name twice: EPS has the file's name in its title.
    for folder in ("one", "two"):
        (tmp_path / folder).mkdir()
        export(figure, data, tmp_path / folder / f"f{suffix}")
    assert (tmp_path / "one" / f"f{suffix}").read_bytes() == (
        tmp_path / "two" / f"f{suffix}"
    ).read_bytes()


def test_a_transparent_background_for_png_and_tiff(
    figure, data, tmp_path: Path
) -> None:
    for suffix in (".png", ".tif"):
        solid, clear = tmp_path / f"s{suffix}", tmp_path / f"c{suffix}"
        export(figure, data, solid)
        export(figure, data, clear, transparent=True)
        corner = (1, 1)  # outside the axes: the figure's own background
        assert Image.open(solid).convert("RGBA").getpixel(corner)[3] == 255
        assert Image.open(clear).convert("RGBA").getpixel(corner)[3] == 0, suffix


def test_export_bytes_takes_the_option_too(figure, data) -> None:
    import io

    png = export_bytes(figure, data, ".png", transparent=True)
    assert Image.open(io.BytesIO(png)).convert("RGBA").getpixel((1, 1))[3] == 0


def test_an_unknown_format_names_the_supported_ones(figure, data, tmp_path) -> None:
    with pytest.raises(ValueError) as error:
        export(figure, data, tmp_path / "f.bmp")
    assert ".tif" in str(error.value) and ".eps" in str(error.value)


def test_a_tiff_has_no_alpha_channel_unless_it_is_transparent(
    figure, data, tmp_path: Path
) -> None:
    """Journals' checkers reject TIFF with an alpha channel."""
    export(figure, data, tmp_path / "solid.tif")
    export(figure, data, tmp_path / "clear.tif", transparent=True)
    assert Image.open(tmp_path / "solid.tif").mode == "RGB"
    assert Image.open(tmp_path / "clear.tif").mode == "RGBA"
