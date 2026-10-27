"""Changing a plot's units or range, as one undo step that keeps everything
read off its axes in step (roadmap F11.4 and F11.5, decision 0041)."""

from __future__ import annotations

import numpy as np
import pytest
from figscribe.units import set_conversion, set_range

from figscribe.commands import History
from figscribe.fit import FitError, refit
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
    LinePlot,
    PredefinedFit,
    Project,
    ReferenceLine,
    ShadedSpan,
    dumps,
)

SOURCE = CsvSource(path="run.csv", sha256="0" * 64, columns=["t", "U", "dU", "V"])
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
