"""Fits and residuals in the renderer: the curve over the data, data minus fit."""

from __future__ import annotations

import matplotlib
import matplotlib.colors
import numpy as np
import pytest

from figscribe.fit import evaluate
from figscribe.model import (
    Axes,
    ErrorbarPlot,
    Figure,
    FitCurve,
    FitResult,
    GridLayout,
    PredefinedFit,
    ResidualPlot,
)
from figscribe.render import render

PARAMETERS = {"a": 1.0, "mu": 5.0, "sigma": 1.4, "c": 0.0}


@pytest.fixture
def figure(ref) -> Figure:
    """Data with a Gaussian fit on top, its residuals below."""
    data = ErrorbarPlot(x=ref("t"), y=ref("U"), yerr=ref("dU"))
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="gaussian"),
        result=FitResult(parameters=PARAMETERS, uncertainties={}),
        linestyle="--",
    )
    residuals = ResidualPlot(target=fit.id, color="k")
    return Figure(
        layout=GridLayout(rows=2),
        axes=[Axes(artists=[data, fit]), Axes(row=1, artists=[residuals])],
    )


def _lines(ax, gid: str):
    return [line for line in ax.get_lines() if line.get_gid() == gid]


def test_the_fit_is_drawn_across_its_data(figure: Figure, data, columns) -> None:
    fit = figure.axes[0].artists[1]
    (line,) = _lines(render(figure, data).axes[0], fit.id)
    xs, ys = line.get_data()
    assert len(xs) == 400
    assert (xs[0], xs[-1]) == (columns["t"].min(), columns["t"].max())
    np.testing.assert_allclose(ys, evaluate(fit.model, PARAMETERS, xs))
    assert line.get_linestyle() == "--"


def test_an_unfitted_curve_draws_nothing(figure: Figure, data) -> None:
    fit = figure.axes[0].artists[1]
    fit.result = None
    fig = render(figure, data)
    assert _lines(fig.axes[0], fit.id) == []
    assert all(not line.get_gid() for line in fig.axes[1].get_lines()[1:])


def test_residuals_are_data_minus_fit(figure: Figure, data, columns) -> None:
    residuals = figure.axes[1].artists[0]
    ax = render(figure, data).axes[1]
    points = [line for line in _lines(ax, residuals.id) if line.get_marker() == "o"]
    xs, ys = points[0].get_data()
    model = figure.axes[0].artists[1].model
    expected = columns["U"] - evaluate(model, PARAMETERS, columns["t"])
    np.testing.assert_allclose(xs, columns["t"])
    np.testing.assert_allclose(ys, expected)
    assert ax.containers[0].has_yerr  # the data's errors carry over
    zero = [line for line in ax.get_lines() if line.get_linestyle() == "--"]
    assert zero and tuple(zero[0].get_ydata()) == (0.0, 0.0)


def test_a_dangling_reference_is_reported(figure: Figure, data) -> None:
    figure.axes[0].artists[1].target = "gone"
    with pytest.raises(ValueError, match="'gone'"):
        render(figure, data)


# --- the look of the residuals (U10) -----------------------------------------


def _drawn_residuals(figure: Figure, data):
    """The panel of the residuals, and the data lines and bars drawn for them."""
    ax = render(figure, data).axes[1]
    residuals = figure.axes[1].artists[0]
    return ax, _lines(ax, residuals.id)


def test_the_line_width_of_residuals_reaches_the_line_and_the_bars(
    figure: Figure, data
) -> None:
    residuals = figure.axes[1].artists[0]
    residuals.linestyle = "-"
    residuals.linewidth = 3.0
    ax, parts = _drawn_residuals(figure, data)
    joined = next(line for line in parts if line.get_marker() == "o")
    assert joined.get_linewidth() == 3.0
    (bars,) = ax.containers[0].lines[2]  # the y error bars
    assert bars.get_linewidth()[0] == 3.0


def test_residuals_without_a_line_width_follow_the_style(figure: Figure, data) -> None:
    assert figure.axes[1].artists[0].linewidth is None
    residuals = figure.axes[1].artists[0]
    residuals.linestyle = "-"
    _, parts = _drawn_residuals(figure, data)
    joined = next(line for line in parts if line.get_marker() == "o")
    assert joined.get_linewidth() == matplotlib.rcParams["lines.linewidth"]


def test_the_zero_line_is_as_it_was_by_default(figure: Figure, data) -> None:
    ax = render(figure, data).axes[1]
    (zero,) = [line for line in ax.get_lines() if tuple(line.get_ydata()) == (0.0, 0.0)]
    assert matplotlib.colors.same_color(zero.get_color(), "0.6")
    assert zero.get_linewidth() == 0.8
    assert zero.get_linestyle() == "--"


def test_the_zero_line_can_be_styled(figure: Figure, data) -> None:
    residuals = figure.axes[1].artists[0]
    residuals.zero_color = "tab:red"
    residuals.zero_linewidth = 2.0
    residuals.zero_linestyle = "-"
    ax = render(figure, data).axes[1]
    (zero,) = [line for line in ax.get_lines() if tuple(line.get_ydata()) == (0.0, 0.0)]
    assert matplotlib.colors.same_color(zero.get_color(), "tab:red")
    assert zero.get_linewidth() == 2.0
    assert zero.get_linestyle() == "-"


def test_the_zero_line_can_be_left_out(figure: Figure, data) -> None:
    figure.axes[1].artists[0].zero_line = False
    ax = render(figure, data).axes[1]
    zero = [line for line in ax.get_lines() if tuple(line.get_ydata()) == (0.0, 0.0)]
    assert zero == []
