"""Settings that do nothing in the state they are in (roadmap B8 item 4).

Each rule in `gui/effect.py` is checked against the renderer: while the rule
says a field does nothing, changing it leaves the figure as it was; once the
setting it waits for is made, the same change shows. The panel greys such
fields out and says why.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

from figscribe.fit import add_fit
from figscribe.gui import Document
from figscribe.gui.effect import RULES, without_effect
from figscribe.gui.properties import PropertyPanel
from figscribe.model import (
    AllanDeviationPlot,
    ArrayRef,
    Axes,
    AxisSpec,
    Colorbar,
    ColumnRef,
    ErrorBand,
    ErrorbarPlot,
    Figure,
    FitCurve,
    FitResult,
    GridLayout,
    ImagePlot,
    Legend,
    LinePlot,
    PredefinedFit,
    Project,
    ReferenceLine,
    ResidualPlot,
    validate_references,
)
from figscribe.render.figure import render

T = np.linspace(0.0, 10.0, 21)
VALUES = {"t": T, "U": np.sin(T), "dU": np.full(21, 0.2), "V": np.cos(T)}


def _data(ref):
    if isinstance(ref, ArrayRef):
        return np.arange(20.0).reshape(4, 5)
    return VALUES[ref.column]


def col(name: str) -> ColumnRef:
    return ColumnRef(source="s", column=name)


def _line(**fields) -> LinePlot:
    return LinePlot(x=col("t"), y=col("U"), **fields)


def _bars(**fields) -> ErrorbarPlot:
    return ErrorbarPlot(x=col("t"), y=col("U"), yerr=col("dU"), **fields)


def _fit(**fields) -> tuple[LinePlot, FitCurve]:
    data = _line(linestyle="none", marker="o")
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="linear"),
        result=FitResult(
            parameters={"a": 0.1, "b": -0.3}, uncertainties={"a": 0.0, "b": 0.0}
        ),
        **fields,
    )
    return data, fit


Case = tuple[Callable[[], tuple[Axes, object]], object, tuple, object]
"""Makes (the panel, the object) with the field doing nothing; a new value
for the field; the setting that makes it count, and its value."""


def _panel(**fields) -> Case:
    def make():
        lines = [_line(label="sine"), _line(label="b")]
        axes = Axes(artists=lines, **copy.deepcopy(fields))
        axes.artists[1].y = col("V")
        return axes, axes

    return make


def _alone(artist_factory, **axes_fields):
    def make():
        artist = artist_factory()
        axes = Axes(artists=[artist], **copy.deepcopy(axes_fields))
        return axes, artist

    return make


def _fitted(**fields):
    def make():
        data, fit = _fit(**fields)
        return Axes(artists=[data, fit]), fit

    return make


def _residuals(data_fields=None, **fields):
    """Data, its fit and the residuals in one panel."""

    def make():
        data, fit = _fit()
        for name, value in (data_fields or {}).items():
            setattr(data, name, value)
        residuals = ResidualPlot(target=fit.id, **fields)
        return Axes(artists=[data, fit, residuals]), residuals

    return make


def _one_panel_of_two_cells() -> tuple[Figure, Figure]:
    """A figure with a grid of two rows and only the first filled."""
    figure = Figure(
        dpi=72,
        layout=GridLayout(rows=2),
        axes=[Axes(y=AxisSpec(label="U", limits=(0.0, 1.0)), artists=[_line()])],
    )
    return figure, figure


SECOND_PANEL = [
    Axes(y=AxisSpec(label="U", limits=(0.0, 1.0)), artists=[_line()]),
    Axes(row=1, y=AxisSpec(label="U", limits=(0.0, 5000.0)), artists=[_line()]),
]
"""A second panel whose numbers are wider, so lining up the labels shows."""

RIGHT = {"y_right": AxisSpec(limits=(-10.0, 10.0))}

CASES: dict[tuple[str, tuple], Case] = {
    ("Axes", ("grid_axis",)): (_panel(), "x", ("grid",), True),
    ("Axes", ("grid_which",)): (_panel(), "both", ("grid",), True),
    ("Axes", ("grid_color",)): (_panel(), "red", ("grid",), True),
    ("Axes", ("grid_linewidth",)): (_panel(), 3.0, ("grid",), True),
    ("Axes", ("grid_linestyle",)): (_panel(), ":", ("grid",), True),
    ("Axes", ("legend", "location")): (
        _panel(legend=Legend(visible=True, position=(0.1, 0.1))),
        "upper left",
        ("legend", "position"),
        None,
    ),
    ("Axes", ("legend", "position")): (
        _panel(),
        (0.1, 0.1),
        ("legend", "visible"),
        True,
    ),
    ("Axes", ("legend", "frame")): (_panel(), False, ("legend", "visible"), True),
    ("Axes", ("legend", "ncols")): (_panel(), 2, ("legend", "visible"), True),
    ("Axes", ("legend", "fontsize")): (_panel(), 14.0, ("legend", "visible"), True),
    ("LinePlot", ("linewidth",)): (
        _alone(lambda: _line(linestyle="none", marker="o")),
        4.0,
        ("linestyle",),
        "-",
    ),
    ("LinePlot", ("markersize",)): (
        _alone(lambda: _line(marker=None)),
        12.0,
        ("marker",),
        "o",
    ),
    ("ErrorbarPlot", ("linewidth",)): (_alone(_bars), 4.0, ("linestyle",), "-"),
    ("ErrorbarPlot", ("capsize",)): (
        _alone(lambda: _bars(band=ErrorBand())),
        6.0,
        ("band",),
        None,
    ),
    ("ErrorbarPlot", ("elinewidth",)): (
        _alone(lambda: _bars(band=ErrorBand())),
        3.0,
        ("band",),
        None,
    ),
    ("LinePlot", ("left_out_color",)): (
        _alone(_line),
        "red",
        ("left_out",),
        [3, 4],
    ),
    ("LinePlot", ("left_out_marker",)): (
        _alone(lambda: _line(marker="o")),
        "x",
        ("left_out",),
        [3, 4],
    ),
    ("LinePlot", ("left_out_linestyle",)): (
        _alone(_line),
        ":",
        ("left_out",),
        [3, 4],
    ),
    ("ReferenceLine", ("axis",)): (
        _alone(lambda: ReferenceLine(at=0.5), **RIGHT),
        "right",
        ("orientation",),
        "horizontal",
    ),
    ("ImagePlot", ("colorbar", "label")): (
        _alone(
            lambda: ImagePlot(
                data=ArrayRef(source="s"), colorbar=Colorbar(visible=False)
            )
        ),
        "counts",
        ("colorbar", "visible"),
        True,
    ),
    ("AllanDeviationPlot", ("sample_interval",)): (
        _alone(lambda: AllanDeviationPlot(values=col("U"), time=col("t"))),
        2.0,
        ("time",),
        None,
    ),
    ("ResidualPlot", ("zero_color",)): (
        _residuals(zero_line=False),
        "red",
        ("zero_line",),
        True,
    ),
    ("ResidualPlot", ("zero_linewidth",)): (
        _residuals(zero_line=False),
        3.0,
        ("zero_line",),
        True,
    ),
    ("ResidualPlot", ("zero_linestyle",)): (
        _residuals(zero_line=False),
        ":",
        ("zero_line",),
        True,
    ),
    ("ResidualPlot", ("linewidth",)): (
        _residuals(),
        4.0,
        ("linestyle",),
        "-",
    ),
    ("Figure", ("align_labels",)): (
        _one_panel_of_two_cells,
        False,
        ("axes",),
        SECOND_PANEL,
    ),
    ("FitCurve", ("extend_curve",)): (
        _fitted(),
        True,
        ("fit_range",),
        (2.0, 6.0),
    ),
    ("FitCurve", ("outside_as_left_out",)): (
        _fitted(),
        True,
        ("fit_range",),
        (2.0, 6.0),
    ),
}


def _set(obj, path: tuple, value) -> None:
    for name in path[:-1]:
        obj = getattr(obj, name)
    setattr(obj, path[-1], value)


def _figure(shown: Axes | Figure) -> Figure:
    return shown if isinstance(shown, Figure) else Figure(dpi=72, axes=[shown])


def _drawn(axes: Axes | Figure) -> str:
    figure = render(_figure(axes), _data)
    FigureCanvasAgg(figure).draw()
    return hashlib.sha1(bytes(figure.canvas.buffer_rgba())).hexdigest()


def _project(axes: Axes | Figure) -> Project:
    return Project(figures=[_figure(axes)])


def test_every_rule_is_checked_here() -> None:
    unchecked = [
        (rule.why, path)
        for rule in RULES
        for path in rule.paths
        if not any((cls.__name__, path) in CASES for cls in rule.owners)
    ]
    assert unchecked == []
    ruled = {
        (cls.__name__, path)
        for rule in RULES
        for cls in rule.owners
        for path in rule.paths
    }
    assert set(CASES) <= ruled


@pytest.mark.parametrize("key", CASES, ids=lambda k: f"{k[0]}.{'.'.join(k[1])}")
def test_a_rule_is_true_to_the_figure(key) -> None:
    make, value, (switch, on) = CASES[key][0], CASES[key][1], CASES[key][2:]
    _, path = key

    axes, obj = make()
    reason = without_effect(obj, path, _project(axes))
    assert reason and reason.startswith("Does nothing while"), reason
    before = _drawn(axes)
    _set(obj, path, value)
    assert _drawn(axes) == before, "the rule says it does nothing, but it does"

    axes, obj = make()
    _set(obj, switch, on)
    assert without_effect(obj, path, _project(axes)) is None
    before = _drawn(axes)
    _set(obj, path, value)
    assert _drawn(axes) != before, "with the setting made, it should show"


# --- in the panel ------------------------------------------------------------


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


@pytest.fixture
def panel(qtbot, document: Document) -> PropertyPanel:
    widget = PropertyPanel(document)
    qtbot.addWidget(widget)
    return widget


def test_grid_settings_are_greyed_while_the_grid_is_off(panel, document) -> None:
    axes = document.figure.axes[0]
    assert not axes.grid
    document.select(axes.id)
    color = panel.editors[("grid_color",)].widget
    assert not color.isEnabled()
    assert color.toolTip().startswith("Does nothing while the grid lines are off")
    panel.editors[("grid",)].widget.click()
    assert panel.editors[("grid_color",)].widget.isEnabled()
    document.undo()
    assert not panel.editors[("grid_color",)].widget.isEnabled()


def test_the_line_width_counts_once_there_is_a_line(panel, document) -> None:
    plot = document.figure.axes[0].artists[0]
    assert plot.linestyle == "none"
    document.select(plot.id)
    assert not panel.editors[("linewidth",)].widget.isEnabled()
    combo = panel.editors[("linestyle",)].widget
    index = combo.findText("Solid")
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    assert panel.editors[("linewidth",)].widget.isEnabled()


def test_the_residuals_line_width_counts_with_error_bars() -> None:
    data = _bars()
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="linear"),
        result=FitResult(parameters={"a": 0.1, "b": -0.3}, uncertainties={}),
    )
    residuals = ResidualPlot(target=fit.id)
    axes = Axes(artists=[data, fit, residuals])
    assert residuals.linestyle == "none"
    assert without_effect(residuals, ("linewidth",), _project(axes)) is None
    before = _drawn(axes)
    residuals.linewidth = 4.0
    assert _drawn(axes) != before


def test_the_zero_line_settings_are_greyed_while_it_is_off(panel, document) -> None:
    data = next(a for a in document.figure.axes[0].artists if a.kind == "errorbar")
    fit = FitCurve(target=data.id, model=PredefinedFit(name="linear"))
    document.push(add_fit(document.project, fit, residuals=True))
    residuals = document.figure.axes[1].artists[0]
    document.select(residuals.id)
    assert panel.editors[("zero_linewidth",)].widget.isEnabled()
    panel.editors[("zero_line",)].widget.click()
    assert not residuals.zero_line
    widget = panel.editors[("zero_linewidth",)].widget
    assert not widget.isEnabled()
    assert widget.toolTip().startswith("Does nothing while the zero line is off")


# --- what the problem list says ---------------------------------------------


def test_grid_lines_at_minor_ticks_without_minor_ticks_are_reported() -> None:
    axes = Axes(
        grid=True,
        grid_which="minor",
        x=AxisSpec(minor_ticks=False),
        y=AxisSpec(minor_ticks=False),
        artists=[_line()],
    )
    issues = [str(issue) for issue in validate_references(_project(axes))]
    assert any("minor ticks" in issue for issue in issues), issues
    axes.y.minor_ticks = True
    issues = [str(issue) for issue in validate_references(_project(axes))]
    assert not any("minor ticks" in issue for issue in issues), issues


def test_aligning_labels_is_greyed_for_one_panel_and_counts_for_two(
    panel, document
) -> None:
    from figscribe.commands import add_panel

    figure = document.figure
    document.select(figure.id)
    toggle = panel.editors[("align_labels",)].widget
    assert not toggle.isEnabled()
    assert toggle.toolTip().startswith(
        "Does nothing while the figure has fewer than two panels"
    )
    document.push(add_panel(document.project, figure.axes[0].id, "below")[0])
    assert panel.editors[("align_labels",)].widget.isEnabled()
    panel.editors[("align_labels",)].widget.click()
    assert document.figure.align_labels is False
    document.undo()
    assert document.figure.align_labels is True
