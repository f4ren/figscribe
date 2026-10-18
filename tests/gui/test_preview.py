"""The preview: what it shows is what the export writes, and clicks select."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt

from figscribe.commands import InsertItem
from figscribe.gui import Document
from figscribe.gui.preview import Preview
from figscribe.model import Axes
from figscribe.render import export
from figscribe.render.figure import MM_PER_INCH


@pytest.fixture
def preview(qtbot, example: Path) -> Preview:
    widget = Preview(Document.open(example))
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_the_figure_keeps_its_size_and_fits_the_widget(preview: Preview) -> None:
    model = preview.document.figure
    assert preview.error is None
    width_in, height_in = preview._figure.get_size_inches()
    assert width_in == pytest.approx(model.width_mm / MM_PER_INCH)
    assert height_in == pytest.approx(model.height_mm / MM_PER_INCH)

    size = preview._image.deviceIndependentSize()
    assert size.width() <= preview.width() and size.height() <= preview.height()
    assert size.width() / size.height() == pytest.approx(
        model.width_mm / model.height_mm, rel=0.01
    )


def test_resizing_changes_only_the_resolution(qtbot, preview: Preview) -> None:
    before = preview.preview_dpi()
    preview.resize(400, 300)
    qtbot.wait(10)
    assert preview.preview_dpi() < before
    width_in, _ = preview._figure.get_size_inches()
    assert width_in == pytest.approx(preview.document.figure.width_mm / MM_PER_INCH)


def test_the_preview_is_the_export(
    preview: Preview, tmp_path: Path, monkeypatch
) -> None:
    """At the export's resolution, the preview image equals the exported PNG."""
    model = preview.document.figure
    monkeypatch.setattr(preview, "preview_dpi", lambda: model.dpi)
    monkeypatch.setattr(preview, "devicePixelRatioF", lambda: 1.0)
    _, image = preview._draw(model)
    shown = np.frombuffer(image.constBits(), np.uint8).reshape(
        image.height(), image.width(), 4
    )

    out = tmp_path / "export.png"
    export(model, preview.document.data, out)
    exported = np.asarray(Image.open(out).convert("RGBA"))
    np.testing.assert_array_equal(shown, exported)


def _widget_point(preview: Preview, ax, x: float, y: float) -> QPointF:
    display = ax.transData.transform((x, y))
    return preview._to_widget(*display)


def test_clicking_a_data_point_selects_its_artist(qtbot, preview: Preview) -> None:
    artist = preview.document.project.figures[0].axes[0].artists[0]
    ax = preview._figure.axes[0]
    data = preview.document.data
    point = _widget_point(preview, ax, data(artist.x)[5], data(artist.y)[5])

    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert preview.document.selected == artist.id
    assert preview.selection_rect() is not None


def test_clicking_empty_axes_selects_the_axes(qtbot) -> None:
    document = Document()
    axes = Axes()
    document.push(InsertItem(document.figure.id, "axes", axes))
    widget = Preview(document)
    qtbot.addWidget(widget)
    widget.resize(600, 400)
    ax = widget._figure.axes[0]
    centre = widget._to_widget(*ax.transAxes.transform((0.5, 0.5)))
    assert widget.object_at(centre) == axes.id


def test_clicking_outside_the_axes_clears_the_selection(
    qtbot, preview: Preview
) -> None:
    artist = preview.document.project.figures[0].axes[0].artists[0]
    preview.document.select(artist.id)
    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton, pos=QPointF(2, 2).toPoint())
    assert preview.document.selected is None


def test_a_missing_data_file_is_shown_not_raised(qtbot, example: Path) -> None:
    (example.parent / "scan.csv").unlink()
    widget = Preview(Document.open(example))
    qtbot.addWidget(widget)
    widget.resize(400, 300)
    assert widget.error is not None and "scan.csv" in widget.error
    assert widget.object_at(QPointF(100, 100)) is None


def test_a_changed_data_file_is_shown_not_raised(qtbot, example: Path) -> None:
    csv = example.parent / "scan.csv"
    csv.write_text(csv.read_text() + "\n", encoding="utf-8")
    widget = Preview(Document.open(example))
    qtbot.addWidget(widget)
    assert "changed" in widget.error
