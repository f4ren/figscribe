"""Changing a plot's units or range, as one undo step that keeps everything
read off its axes in step (roadmap F11.4 and F11.5, decision 0041)."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.commands import History
from figscribe.convert import plot_data
from figscribe.fit import FitError, add_fit, refit
from figscribe.model import (
    Annotation,
    Axes,
    AxisSpec,
    ColumnRef,
    Conversion,
    CsvSource,
    ErrorbarPlot,
    Figure,
    FitCurve,
    GridLayout,
    LinePlot,
    PredefinedFit,
    Project,
    ReferenceLine,
    ResidualPlot,
    ShadedSpan,
    dumps,
)
from figscribe.units import set_conversion, set_range

SOURCE = CsvSource(
    path="run.csv", sha256="0" * 64, columns=["t", "U", "dU", "V", "gap"]
)
T = 1000.0 + 360.0 * np.arange(41)  # s, every 6 min for 4 h, starting at 1000 s
COLUMNS = {
    "t": T,
    "U": np.exp(-(((T - T[20]) / 3600) ** 2)),
    "dU": np.full(41, 0.05),
    "V": np.linspace(0, 1, 41),
}
HOURS = Conversion(factor=1 / 3600, from_start=True, unit="h")


def data(ref: ColumnRef) -> np.ndarray:
    return COLUMNS[ref.column]


def col(name: str) -> ColumnRef:
    return ColumnRef(source=SOURCE.id, column=name)


def _project(*others) -> Project:
    plot = ErrorbarPlot(
        x=col("t"), y=col("U"), yerr=col("dU"), x_range=(3600.0, 12000.0)
    )
    fit = FitCurve(
        target=plot.id,
        model=PredefinedFit(name="gaussian"),
        fit_range=(4000.0, 11000.0),
    )
    axes = Axes(
        x=AxisSpec(label="t", unit="s", limits=(1000.0, 15400.0), major_step=3600.0),
        y=AxisSpec(label="U", unit="V"),
        artists=[
            plot,
            fit,
            ReferenceLine(at=8200.0),
            ShadedSpan(start=4600.0, end=8200.0),
            Annotation(text="peak", position=(8200.0, 1.0), arrow_to=(8200.0, 0.9)),
            *others,
        ],
    )
    project = Project(sources=[SOURCE], figures=[Figure(axes=[axes])])
    refit(project, fit.id, data).apply(project)
    return project


def _parts(project: Project):
    return project.figures[0].axes[0], project.figures[0].axes[0].artists


def test_the_axis_and_everything_on_it_follow_a_conversion() -> None:
    project = _project()
    before = dumps(project)
    history = History(project)
    axes, (plot, fit, line, span, note) = _parts(project)
    history.push(set_conversion(project, plot.id, "x", HOURS, data))

    axes, (plot, fit, line, span, note) = _parts(project)
    assert history.undo_text == "Show x in h"
    assert plot.x_conversion == HOURS
    # 1000 s is the start, so 3600 s is 0.722… h after it.
    assert plot.x_range == pytest.approx(((3600 - 1000) / 3600, 11000 / 3600))
    assert fit.fit_range == pytest.approx((3000 / 3600, 10000 / 3600))
    assert fit.result.parameters["mu"] == pytest.approx((T[20] - 1000) / 3600)
    assert axes.x.unit == "h"
    assert axes.x.limits == pytest.approx((0.0, 4.0))
    assert axes.x.major_step == pytest.approx(1.0)
    assert line.at == pytest.approx(2.0)
    assert (span.start, span.end) == pytest.approx((1.0, 2.0))
    assert note.position == pytest.approx((2.0, 1.0))
    assert note.arrow_to == pytest.approx((2.0, 0.9))

    history.undo()
    assert dumps(project) == before


def test_another_plot_on_the_axis_keeps_what_is_drawn_against_it() -> None:
    other = LinePlot(x=col("t"), y=col("V"))
    project = _project(other)
    axes, (plot, *_rest) = _parts(project)
    History(project).push(set_conversion(project, plot.id, "x", HOURS, data))
    axes, (plot, fit, line, *_rest) = _parts(project)
    assert axes.x.unit == "h"  # the unit text follows still
    assert axes.x.limits == (1000.0, 15400.0)  # in s, as the other plot is
    assert line.at == 8200.0
    assert plot.x_range == pytest.approx(((3600 - 1000) / 3600, 11000 / 3600))


def test_y_converts_its_axis_and_fits_again() -> None:
    project = _project()
    axes, (plot, fit, *_rest) = _parts(project)
    mV = Conversion(factor=1000.0, unit="mV")
    History(project).push(set_conversion(project, plot.id, "y", mV, data))
    axes, (plot, fit, *_rest) = _parts(project)
    assert axes.y.unit == "mV"
    assert fit.result.parameters["a"] == pytest.approx(1000.0, rel=0.01)


def test_taking_a_conversion_back_empties_the_unit_it_gave() -> None:
    project = _project()
    plot = _parts(project)[1][0]
    history = History(project)
    history.push(set_conversion(project, plot.id, "x", HOURS, data))
    history.push(set_conversion(project, plot.id, "x", None, data))
    axes, (plot, fit, *_rest) = _parts(project)
    assert history.undo_text == "Show x as in the file"
    assert axes.x.unit is None  # figscribe does not know the file's unit
    assert plot.x_range == pytest.approx((3600.0, 11000.0 + 1000.0))
    assert axes.x.limits == pytest.approx((1000.0, 15400.0))


def test_a_range_fits_again_and_is_refused_with_too_few_points() -> None:
    project = _project()
    plot = _parts(project)[1][0]
    history = History(project)
    history.push(set_range(project, plot.id, (5000.0, 9000.0), data))
    assert history.undo_text == "Use only x from 5000 to 9000"
    fit = _parts(project)[1][1]
    assert fit.result is not None
    before = dumps(project)
    with pytest.raises(FitError):
        set_range(project, plot.id, (5000.0, 5400.0), data)  # one point
    assert dumps(project) == before
    history.push(set_range(project, plot.id, None, data))
    assert history.undo_text == "Use every row"


# --- the problem list ---------------------------------------------------------


def _problems(*artists) -> list[str]:
    from figscribe.model import validate_references

    project = Project(
        sources=[SOURCE], figures=[Figure(axes=[Axes(artists=list(artists))])]
    )
    return [str(issue) for issue in validate_references(project, data)]


def test_a_fit_range_beyond_the_plots_range_is_a_problem() -> None:
    plot = LinePlot(x=col("t"), y=col("U"), x_range=(3600.0, 7200.0))
    fit = FitCurve(
        target=plot.id, model=PredefinedFit(name="linear"), fit_range=(1000.0, 5000.0)
    )
    (problem,) = [p for p in _problems(plot, fit) if "fit_range" in p]
    assert "reaches beyond the plot's range 3600 to 7200" in problem


def test_an_allan_fit_range_is_in_tau_not_in_the_time_of_the_range() -> None:
    """The range of an Allan deviation is the time since the first sample, the
    fit range is τ: one is not beyond the other (decision 0064)."""
    from figscribe.model import AllanDeviationPlot, ExpressionFit

    plot = AllanDeviationPlot(values=col("U"), x_range=(0.0, 4.0))
    fit = FitCurve(
        target=plot.id,
        model=ExpressionFit(expression="a / sqrt(x)", parameters=["a"]),
        fit_range=(1.0, 10.0),
    )
    assert not [p for p in _problems(plot, fit) if "reaches beyond" in p]


def test_a_fit_with_no_point_left_is_a_problem() -> None:
    """Its figure draws no curve, so the list says why (decision 0059)."""
    from figscribe.model import FitResult

    result = FitResult(
        parameters={"a": 1.0, "b": 0.0}, uncertainties={"a": 0.1, "b": 0.1}
    )
    model = PredefinedFit(name="linear")

    def left(*changes) -> list[str]:
        plot = LinePlot(x=col("t"), y=col("U"))
        fit = FitCurve(target=plot.id, model=model, result=result)
        for name, value in changes:
            setattr(plot if name == "left_out" else fit, name, value)
        return [p for p in _problems(plot, fit) if "no point is left" in p]

    (problem,) = left(("fit_range", (1e6, 2e6)))
    assert "fit is not drawn" in problem
    assert left(("left_out", list(range(41))))  # every row
    assert not left()
    assert not left(("fit_range", (2000.0, 5000.0)))
    assert not left(("left_out", [0, 1, 2]))
    # rows that the data does not have are another problem, said elsewhere
    assert not left(("left_out", [100]))
    plot = LinePlot(x=col("t"), y=col("U"))
    not_run = FitCurve(target=plot.id, model=model, fit_range=(1e6, 2e6))
    assert not [p for p in _problems(plot, not_run) if "no point is left" in p]


def test_a_range_with_nothing_in_it_is_a_problem() -> None:
    from figscribe.model import Histogram

    plot = LinePlot(x=col("t"), y=col("U"), x_range=(0.0, 10.0))
    counts = Histogram(values=col("U"), x_range=(5.0, 6.0))
    problems = _problems(plot, counts)
    assert any("no row lies within the range 0 to 10" in p for p in problems)
    assert any("no value lies within the range 5 to 6" in p for p in problems)


def test_an_allan_deviation_needs_an_unbroken_range() -> None:
    from figscribe.model import AllanDeviationPlot

    COLUMNS["gap"] = np.where(np.arange(41) == 30, np.nan, 1e-12)
    early = AllanDeviationPlot(values=col("gap"), time=col("t"), x_range=(0.0, 7200.0))
    late = AllanDeviationPlot(
        values=col("gap"), time=col("t"), x_range=(7200.0, 14400.0)
    )
    assert _problems(early) == []  # the gap at row 30 lies after 2 h
    assert any("needs an unbroken series" in p for p in _problems(late))
    nothing = AllanDeviationPlot(values=col("gap"), time=col("t"), x_range=(9e9, 1e10))
    assert any("no sample lies within" in p for p in _problems(nothing))


# --- a formula for the units (F13, decision 0047) ---------------------------------

KELVIN_TO_CELSIUS = Conversion(formula="x - 273.15", unit="°C")


def test_a_formula_moves_the_axis_and_everything_on_it_by_its_offset() -> None:
    project = _project()
    before = dumps(project)
    history = History(project)
    plot = _parts(project)[1][0]
    history.push(set_conversion(project, plot.id, "x", KELVIN_TO_CELSIUS, data))

    axes, (plot, fit, line, span, note) = _parts(project)
    assert history.undo_text == "Show x in °C"
    assert plot.x_conversion == KELVIN_TO_CELSIUS
    assert plot.x_range == pytest.approx((3600 - 273.15, 12000 - 273.15))
    assert fit.fit_range == pytest.approx((4000 - 273.15, 11000 - 273.15))
    assert axes.x.unit == "°C"
    assert axes.x.limits == pytest.approx((1000 - 273.15, 15400 - 273.15))
    assert axes.x.major_step == pytest.approx(3600.0)  # a width is not shifted
    assert line.at == pytest.approx(8200 - 273.15)
    assert (span.start, span.end) == pytest.approx((4600 - 273.15, 8200 - 273.15))
    assert note.position == pytest.approx((8200 - 273.15, 1.0))

    history.undo()
    assert dumps(project) == before


def test_changing_from_one_formula_to_another_maps_through_the_raw_values() -> None:
    project = _project()
    history = History(project)
    plot = _parts(project)[1][0]
    history.push(set_conversion(project, plot.id, "x", KELVIN_TO_CELSIUS, data))
    history.push(
        set_conversion(
            project, plot.id, "x", Conversion(formula="(x - 32) / 1.8"), data
        )
    )
    axes, (plot, fit, line, *_) = _parts(project)
    assert axes.x.limits == pytest.approx(((1000 - 32) / 1.8, (15400 - 32) / 1.8))
    assert axes.x.major_step == pytest.approx(3600 / 1.8)
    assert line.at == pytest.approx((8200 - 32) / 1.8)

    history.push(set_conversion(project, plot.id, "x", None, data))
    axes, (plot, *_) = _parts(project)
    assert axes.x.limits == pytest.approx((1000.0, 15400.0))
    assert plot.x_range == pytest.approx((3600.0, 12000.0))


def test_a_formula_on_y_scales_the_errors_but_does_not_shift_them() -> None:
    project = _project()
    plot = _parts(project)[1][0]
    History(project).push(
        set_conversion(
            project, plot.id, "y", Conversion(formula="x * 1000 + 5", unit="mV"), data
        )
    )
    shown = plot_data(_parts(project)[1][0], data)
    assert np.allclose(shown.y, COLUMNS["U"] * 1000 + 5)
    assert np.allclose(shown.yerr, 50.0)  # 0.05 V


# --- broken axes ---------------------------------------------------------------


def _broken(*below) -> Project:
    """_project with a break, and a second panel that shares x and its break."""
    project = _project()
    figure = project.figures[0]
    figure.layout = GridLayout(rows=2, share_x="col")
    figure.axes[0].x.breaks = [(12000.0, 13000.0), (14000.0, 15000.0)]
    figure.axes.append(
        Axes(
            row=1,
            x=AxisSpec(breaks=[(12000.0, 13000.0), (14000.0, 15000.0)]),
            artists=list(below),
        )
    )
    return project


@pytest.mark.parametrize(
    ("conversion", "expected"),
    [
        (HOURS, [(11 / 3.6, 12 / 3.6), (13 / 3.6, 14 / 3.6)]),
        (
            KELVIN_TO_CELSIUS,
            [(12000 - 273.15, 13000 - 273.15), (14000 - 273.15, 15000 - 273.15)],
        ),
    ],
    ids=["factor", "formula"],
)
def test_breaks_follow_a_conversion_on_every_panel_sharing_the_axis(
    conversion, expected
) -> None:
    project = _broken()
    before = dumps(project)
    history = History(project)
    plot = _parts(project)[1][0]
    history.push(set_conversion(project, plot.id, "x", conversion, data))

    for axes in project.figures[0].axes:
        assert np.array(axes.x.breaks) == pytest.approx(np.array(expected))
    history.undo()
    assert dumps(project) == before


def test_breaks_stay_while_a_panel_sharing_the_axis_shows_other_data() -> None:
    project = _broken(LinePlot(x=col("t"), y=col("V")))
    plot = _parts(project)[1][0]
    History(project).push(set_conversion(project, plot.id, "x", HOURS, data))
    for axes in project.figures[0].axes:
        assert axes.x.breaks == [(12000.0, 13000.0), (14000.0, 15000.0)]


# --- panels that share the axis ------------------------------------------------


def _with_residuals() -> Project:
    """_project with a fit's residuals below, as *Fit…* adds them: the panel
    takes over the x axis's settings, and its label."""
    project = _project()
    plot = _parts(project)[1][0]
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, data).apply(project)
    below = project.figures[0].axes[1]
    below.artists.append(ReferenceLine(at=8200.0))
    return project


def test_every_panel_sharing_the_axis_follows_a_conversion() -> None:
    project = _with_residuals()
    before = dumps(project)
    history = History(project)
    plot = _parts(project)[1][0]
    history.push(set_conversion(project, plot.id, "x", HOURS, data))

    above, below = project.figures[0].axes
    for axes in (above, below):
        assert axes.x.limits == pytest.approx((0.0, 4.0))
        assert axes.x.major_step == pytest.approx(1.0)
    assert (below.x.label, below.x.unit) == ("t", "h")
    assert above.x.label is None  # no label appears where there was none
    assert below.artists[-1].at == pytest.approx(2.0)

    history.undo()
    assert dumps(project) == before


@pytest.mark.parametrize("shown", ["plot", "residuals of another plot"])
def test_a_sharing_panel_with_other_data_keeps_its_own_numbers(shown) -> None:
    project = _with_residuals()
    figure = project.figures[0]
    other = LinePlot(x=col("t"), y=col("V"))
    if shown == "plot":
        figure.axes[1].artists.append(other)
    else:  # of a plot in another column: only its residuals stand against x here
        fit = FitCurve(target=other.id, model=PredefinedFit(name="linear"))
        figure.layout.cols = 2
        figure.axes.append(Axes(row=0, col=1, artists=[other, fit]))
        figure.axes[1].artists.append(ResidualPlot(target=fit.id))
    plot = _parts(project)[1][0]
    History(project).push(set_conversion(project, plot.id, "x", HOURS, data))

    above, below = project.figures[0].axes[:2]
    assert above.x.limits == pytest.approx((0.0, 4.0))  # the plot's own panel
    assert below.x.limits == (1000.0, 15400.0)
    assert below.x.unit == "s"  # nor is it called what its data are not
    assert [a for a in below.artists if isinstance(a, ReferenceLine)][0].at == 8200.0


def _stacked() -> Project:
    """Two panels sharing x, each with a plot of its own and a line at 8200 s."""
    top = LinePlot(x=col("t"), y=col("U"))
    bottom = LinePlot(x=col("t"), y=col("V"))
    panels = [
        Axes(
            x=AxisSpec(label="t", unit="s"),
            artists=[top, ReferenceLine(at=8200.0)],
        ),
        Axes(
            row=1,
            x=AxisSpec(label="t", unit="s", limits=(1000.0, 15400.0)),
            artists=[bottom, ReferenceLine(at=8200.0)],
        ),
    ]
    figure = Figure(layout=GridLayout(rows=2, share_x="col"), axes=panels)
    return Project(sources=[SOURCE], figures=[figure])


def test_panels_with_data_of_their_own_each_follow_their_plot() -> None:
    project = _stacked()
    before = dumps(project)
    history = History(project)
    top, bottom = (axes.artists[0] for axes in project.figures[0].axes)
    history.push(set_conversion(project, top.id, "x", HOURS, data))
    above, below = project.figures[0].axes
    assert above.artists[1].at == pytest.approx(2.0)
    assert (below.x.unit, below.x.limits) == ("s", (1000.0, 15400.0))
    assert below.artists[1].at == 8200.0

    history.push(set_conversion(project, bottom.id, "x", HOURS, data))
    above, below = project.figures[0].axes
    assert below.x.unit == "h"
    assert below.x.limits == pytest.approx((0.0, 4.0))
    assert [a.artists[1].at for a in (above, below)] == pytest.approx([2.0, 2.0])

    history.undo()
    history.undo()
    assert dumps(project) == before


def test_there_and_back_leaves_the_numbers_as_they_were() -> None:
    project = _stacked()
    history = History(project)
    top = project.figures[0].axes[0].artists[0]
    history.push(set_conversion(project, top.id, "x", HOURS, data))
    history.push(set_conversion(project, top.id, "x", None, data))
    above, below = project.figures[0].axes
    assert [a.artists[1].at for a in (above, below)] == pytest.approx([8200.0] * 2)
    assert below.x.limits == (1000.0, 15400.0)


def _with_marked_residuals() -> Project:
    """_with_residuals with a range, a step and a line on the residuals' y."""
    project = _with_residuals()
    below = project.figures[0].axes[1]
    below.y.limits = (-0.01, 0.01)
    below.y.major_step = 0.005
    below.artists.append(ReferenceLine(orientation="horizontal", at=0.002))
    return project


@pytest.mark.parametrize(
    "conversion",
    [
        Conversion(factor=1000.0, unit="mV"),
        # The offset moves the data, not what lies between data and fit.
        Conversion(formula="x * 1000 + 5", unit="mV"),
    ],
    ids=["factor", "formula"],
)
def test_the_residuals_y_axis_follows_without_the_offset(conversion) -> None:
    project = _with_marked_residuals()
    before = dumps(project)
    history = History(project)
    plot = _parts(project)[1][0]
    history.push(set_conversion(project, plot.id, "y", conversion, data))

    below = project.figures[0].axes[1]
    assert (below.y.label, below.y.unit) == ("Residual", "mV")
    assert below.y.limits == pytest.approx((-10.0, 10.0))
    assert below.y.major_step == pytest.approx(5.0)
    assert below.artists[-1].at == pytest.approx(2.0)

    history.undo()
    assert dumps(project) == before


def test_residuals_beside_those_of_another_plot_keep_their_numbers() -> None:
    project = _with_marked_residuals()
    figure = project.figures[0]
    other = LinePlot(x=col("t"), y=col("V"))
    fit = FitCurve(target=other.id, model=PredefinedFit(name="linear"))
    figure.axes[0].artists += [other, fit]
    figure.axes[1].artists.append(ResidualPlot(target=fit.id))
    plot = _parts(project)[1][0]
    mV = Conversion(factor=1000.0, unit="mV")
    History(project).push(set_conversion(project, plot.id, "y", mV, data))

    below = project.figures[0].axes[1]
    assert below.y.limits == (-0.01, 0.01)
    assert below.y.unit == "V"  # nor renamed: the others are in V still


def test_residuals_on_a_right_axis_that_is_not_there_stand_on_the_left() -> None:
    """The panel has no right y axis, so they are drawn on the left one, where
    another plot's numbers are."""
    project = _with_marked_residuals()
    figure = project.figures[0]
    below = figure.axes[1]
    below.artists[0].axis = "right"
    below.artists.append(LinePlot(x=col("t"), y=col("V")))
    plot = _parts(project)[1][0]
    mV = Conversion(factor=1000.0, unit="mV")
    History(project).push(set_conversion(project, plot.id, "y", mV, data))
    assert project.figures[0].axes[1].y.limits == (-0.01, 0.01)


def test_residuals_follow_a_plot_meant_for_a_right_axis_that_is_not_there() -> None:
    project = _with_marked_residuals()
    plot = _parts(project)[1][0]
    plot.axis = "right"
    mV = Conversion(factor=1000.0, unit="mV")
    History(project).push(set_conversion(project, plot.id, "y", mV, data))
    assert project.figures[0].axes[1].y.limits == pytest.approx((-10.0, 10.0))


def test_residuals_that_do_not_share_x_follow_it_all_the_same() -> None:
    """*Fit…* puts them in an empty panel below without sharing the axis."""
    project = _project()
    figure = project.figures[0]
    figure.layout.rows = 2
    figure.axes.append(Axes(row=1))
    plot = _parts(project)[1][0]
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, data).apply(project)
    assert project.figures[0].layout.share_x == "none"
    History(project).push(set_conversion(project, plot.id, "x", HOURS, data))
    below = project.figures[0].axes[1]
    assert below.x.unit == "h"
    assert below.x.limits == pytest.approx((0.0, 4.0))


# --- an SI prefix of the old unit ----------------------------------------------


def _shown_in_milli() -> Project:
    """_with_marked_residuals, both y axes showing their volts as mV."""
    project = _with_marked_residuals()
    for axes in project.figures[0].axes:
        axes.y.prefix = "m"
        axes.y.unit = "V"
    return project


def test_a_new_unit_drops_the_prefix_of_the_old_one() -> None:
    project = _shown_in_milli()
    before = dumps(project)
    history = History(project)
    plot = _parts(project)[1][0]
    mV = Conversion(factor=1000.0, unit="mV")
    history.push(set_conversion(project, plot.id, "y", mV, data))
    for axes in project.figures[0].axes:
        assert (axes.y.unit, axes.y.prefix) == ("mV", None)  # not "mmV"
    history.undo()
    assert dumps(project) == before


def test_a_conversion_that_keeps_the_unit_keeps_the_prefix() -> None:
    """Such as a calibration factor: the axis is in volts as before."""
    project = _shown_in_milli()
    plot = _parts(project)[1][0]
    calibrated = Conversion(factor=1.02, unit="V")
    History(project).push(set_conversion(project, plot.id, "y", calibrated, data))
    for axes in project.figures[0].axes:
        assert (axes.y.unit, axes.y.prefix) == ("V", "m")


def test_emptying_the_unit_empties_its_prefix() -> None:
    project = _project()
    plot = _parts(project)[1][0]
    history = History(project)
    history.push(set_conversion(project, plot.id, "x", HOURS, data))
    project.figures[0].axes[0].x.prefix = "m"
    history.push(set_conversion(project, plot.id, "x", None, data))
    spec = project.figures[0].axes[0].x
    assert (spec.unit, spec.prefix) == (None, None)


def _side_by_side() -> Project:
    """Two panels sharing y, each with a plot of its own, volts shown as mV."""
    axes = [
        Axes(
            col=i,
            y=AxisSpec(label="U", unit="V", prefix="m"),
            artists=[LinePlot(x=col("t"), y=col(name))],
        )
        for i, name in enumerate(("U", "V"))
    ]
    figure = Figure(layout=GridLayout(cols=2, share_y="row"), axes=axes)
    return Project(sources=[SOURCE], figures=[figure])


def test_a_shared_axis_never_gets_two_prefixes() -> None:
    """Panels sharing an axis have one formatter: a prefix left on one of them
    would scale the numbers of both. While the other is still in V, the first
    one keeps it too and reads "mmV", with right numbers; once both are in mV it
    goes."""
    project = _side_by_side()
    before = dumps(project)
    history = History(project)
    first, second = (axes.artists[0] for axes in project.figures[0].axes)
    mV = Conversion(factor=1000.0, unit="mV")
    history.push(set_conversion(project, first.id, "y", mV, data))
    assert [a.y.prefix for a in project.figures[0].axes] == ["m", "m"]

    history.push(set_conversion(project, second.id, "y", mV, data))
    assert [a.y.prefix for a in project.figures[0].axes] == [None, None]
    history.undo()
    history.undo()
    assert dumps(project) == before


def test_a_calibration_keeps_the_prefix_on_the_residual_stack_too() -> None:
    """*Fit…* leaves the upper panel without a unit but with the prefix."""
    project = _project()
    project.figures[0].axes[0].x.prefix = "m"
    plot = _parts(project)[1][0]
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, data).apply(project)
    calibrated = Conversion(factor=1.02, unit="s")
    History(project).push(set_conversion(project, plot.id, "x", calibrated, data))
    assert [a.x.prefix for a in project.figures[0].axes] == ["m", "m"]
