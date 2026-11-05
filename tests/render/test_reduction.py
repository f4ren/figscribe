"""A reduced plot in the renderer: fewer points, derived errors, fits on them."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.commands import History
from figscribe.fit import refit, residuals, run_fit
from figscribe.model import (
    Axes,
    ErrorbarPlot,
    Figure,
    FitCurve,
    LinePlot,
    PredefinedFit,
    Project,
    Reduction,
    ScatterPlot,
)
from figscribe.render import render


@pytest.fixture
def columns() -> dict[str, np.ndarray]:
    t = np.arange(100.0)
    noise = np.sin(7 * t)
    return {"t": t, "U": 3.0 + 0.5 * t + noise, "dU": np.full(100, 0.4)}


def _draw(plot, data):
    fig = render(Figure(axes=[Axes(artists=[plot])]), data)
    return fig.axes[0]


def test_a_reduced_line_draws_one_point_per_group(ref, data, columns) -> None:
    plot = LinePlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    (line,) = _draw(plot, data).get_lines()
    xs, ys = line.get_data()
    assert len(xs) == 10
    assert np.allclose(ys, columns["U"].reshape(10, 10).mean(axis=1))


def test_error_bars_show_the_derived_errors(ref, data, columns) -> None:
    plot = ErrorbarPlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    ax = _draw(plot, data)
    (bars,) = ax.collections
    segments = bars.get_segments()
    assert len(segments) == 10
    groups = columns["U"].reshape(10, 10)
    half = np.array([s[1, 1] - s[0, 1] for s in segments]) / 2
    assert np.allclose(half, groups.std(axis=1, ddof=1) / np.sqrt(10))


def test_a_reduced_points_plot_has_no_error_bars(ref, data) -> None:
    plot = ScatterPlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    ax = _draw(plot, data)
    (points,) = ax.collections
    assert len(points.get_offsets()) == 10


def test_rows_left_out_are_not_drawn_apart_while_reduced(ref, data) -> None:
    def drawn(left_out):
        plot = ErrorbarPlot(
            x=ref("t"), y=ref("U"), left_out=left_out, reduction=Reduction(count=10)
        )
        ax = _draw(plot, data)
        return len(ax.get_lines()), len(ax.collections)

    assert drawn([57]) == drawn([])  # nothing grey beside the points


def test_rows_left_out_beyond_the_data_say_so(ref, data) -> None:
    from figscribe.io.errors import DataError

    plot = LinePlot(
        x=ref("t"), y=ref("U"), left_out=[500], reduction=Reduction(count=10)
    )
    with pytest.raises(DataError, match="row 501 is left out"):
        _draw(plot, data)


def test_a_fit_on_a_reduced_plot_uses_the_reduced_points_as_absolute(
    ref, data, columns, source
) -> None:
    plot = LinePlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    project = Project(
        sources=[source], figures=[Figure(axes=[Axes(artists=[plot, fit])])]
    )
    History(project).push(refit(project, fit.id, data))
    result = project.figures[0].axes[0].artists[1].result
    groups = columns["U"].reshape(10, 10)
    x = columns["t"].reshape(10, 10).mean(axis=1)
    sigma = groups.std(axis=1, ddof=1) / np.sqrt(10)
    expected = run_fit(fit.model, {"a": 1.0, "b": 0.0}, x, groups.mean(axis=1), sigma)
    assert result.parameters["a"] == pytest.approx(expected.parameters["a"], rel=1e-6)
    assert result.uncertainties["a"] == pytest.approx(
        expected.uncertainties["a"], rel=1e-6
    )
    assert result.reduced_chi_square == pytest.approx(expected.reduced_chi_square)


def test_a_group_without_an_error_is_not_fitted(ref, data, source) -> None:
    t = np.arange(51.0)  # the last group is row 51 alone
    columns = {"t": t, "U": t**1.5 + np.sin(t), "dU": np.ones(51)}
    plot = LinePlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    project = Project(
        sources=[source], figures=[Figure(axes=[Axes(artists=[plot, fit])])]
    )
    History(project).push(refit(project, fit.id, lambda r: columns[r.column]))
    assert project.figures[0].axes[0].artists[1].result.converged
    assert residuals(project, fit.id, lambda r: columns[r.column]).used == 5
