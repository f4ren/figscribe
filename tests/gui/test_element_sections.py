"""The settings of each kind of element, by what they are for (roadmap U11,
decisions 0060 to 0062): which sections, in which order, with which fields.
Proposed while the user was away; this test says what was built."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import Document
from figscribe.gui.properties import PropertyPanel

from .everything import build


@pytest.fixture(scope="module")
def project_file(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("everything"))


def _first(project, kind: type):
    for figure in project.figures:
        for axes in figure.axes:
            for artist in axes.artists:
                if isinstance(artist, kind):
                    return artist
    raise AssertionError(kind)


def _sections(qtbot, project_file: Path, kind: type):
    document = Document.open(project_file)
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    panel.resize(400, 900)
    panel.show()
    document.select(_first(document.project, kind).id)
    fields = {
        title: [
            ".".join(path)
            for path, editor in panel.editors.items()
            if section.isAncestorOf(editor.widget)
        ]
        for title, section in panel.sections.items()
    }
    return panel, fields


def _case(name: str):
    import figscribe.model as model

    return getattr(model, name)


EXPECTED = {
    "Annotation": {
        "Text": ["text", "fontsize", "color", "background"],
        "Place": ["position", "coords", "arrow_to", "axis"],
        "More": ["label", "alpha", "visible", "zorder"],
    },
    "ReferenceLine": {
        "Label and data": ["label", "orientation", "at", "axis"],
        "Look": ["color", "linestyle", "linewidth"],
        "More": ["alpha", "visible", "zorder"],
    },
    "ShadedSpan": {
        "Label and data": ["label", "orientation", "start", "end", "axis"],
        "Look": ["color", "alpha"],
        "More": ["visible", "zorder"],
    },
    "FitCurve": {
        "Label and data": ["label", "axis"],
        "Look": [
            "color",
            "linestyle",
            "linewidth",
            "extend_curve",
            "outside_as_left_out",
        ],
        "More": ["alpha", "visible", "zorder"],
    },
    "ResidualPlot": {
        "Label and data": ["axis"],
        "Look": ["color", "marker", "markersize", "linestyle", "linewidth"],
        "Zero line": ["zero_line", "zero_color", "zero_linewidth", "zero_linestyle"],
        "More": ["label", "alpha", "visible", "zorder"],
    },
    "Histogram": {
        "Label and data": ["label", "axis", "values", "bins", "density"],
        "Units and rows": ["x_conversion", "x_range"],
        "Look": ["color", "histtype"],
        "More": ["alpha", "visible", "zorder"],
    },
    "AllanDeviationPlot": {
        "Label and data": [
            "label",
            "axis",
            "values",
            "data_type",
            "sample_interval",
            "time",
            "taus",
        ],
        "Units and rows": ["x_conversion", "x_range"],
        "Look": [
            "color",
            "marker",
            "markersize",
            "linestyle",
            "linewidth",
            "error_bars",
        ],
        "More": ["alpha", "visible", "zorder"],
    },
    "ImagePlot": {
        "Label and data": ["axis", "data"],
        "Look": [
            "cmap",
            "norm",
            "vmin",
            "vmax",
            "colorbar",
            "colorbar.visible",
            "colorbar.label",
        ],
        "Pixel grid": ["extent", "origin", "aspect"],
        "More": ["label", "alpha", "visible", "zorder"],
    },
    "ColorMesh": {
        "Label and data": ["axis", "c", "x", "y"],
        "Look": [
            "cmap",
            "norm",
            "vmin",
            "vmax",
            "colorbar",
            "colorbar.visible",
            "colorbar.label",
        ],
        "More": ["label", "alpha", "visible", "zorder"],
    },
}


@pytest.mark.parametrize("name", list(EXPECTED))
def test_the_sections_of_each_kind(qtbot, project_file: Path, name: str) -> None:
    panel, fields = _sections(qtbot, project_file, _case(name))
    assert fields == EXPECTED[name]
    assert list(panel.sections) == list(EXPECTED[name])  # in this order
    assert not panel.sections["More"].expanded
    for title in panel.sections:
        if title not in ("More", "Pixel grid"):
            assert panel.sections[title].expanded, title
    assert "Color bar" not in panel.sections  # its settings are under its box


def test_a_legend_entry_is_called_that_everywhere(qtbot, project_file) -> None:
    for name in (
        "ReferenceLine",
        "ShadedSpan",
        "FitCurve",
        "Histogram",
        "AllanDeviationPlot",
    ):
        panel, _ = _sections(qtbot, project_file, _case(name))
        caption, _tip = panel._captions[("label",)]
        assert caption.text() == "Legend entry", name


def test_the_result_of_a_fit_sits_under_its_first_section(qtbot, project_file) -> None:
    from figscribe.model import FitCurve

    panel, _ = _sections(qtbot, project_file, FitCurve)
    layout = panel.widget().layout()
    items = [layout.itemAt(i).widget() for i in range(layout.count())]
    first = items.index(panel.sections["Label and data"])
    assert items[first + 1] is not panel.sections["Look"]  # the card, between
