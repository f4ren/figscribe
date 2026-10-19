"""Fits and residuals in the renderer: the curve over the data, data minus fit."""

from __future__ import annotations

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
