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


# --- the curve beyond the data (F1.9) ----------------------------------------


def _curve(figure: Figure, data) -> np.ndarray:
    """Where the fitted curve of the first panel was sampled."""
    fit = figure.axes[0].artists[1]
    line = _lines(render(figure, data).axes[0], fit.id)[0]
    return np.asarray(line.get_xdata())


def test_a_given_range_draws_the_curve_there(figure: Figure, data) -> None:
    figure.axes[0].artists[1].curve_range = (-5.0, 25.0)
    figure.axes[0].artists[1].mark_extrapolated = False  # one plain curve
    xs = _curve(figure, data)
    assert (len(xs), xs[0], xs[-1]) == (400, -5.0, 25.0)
    low, high = render(figure, data).axes[0].get_xlim()
    assert low < -5.0 and high > 25.0  # the automatic range follows the curve


@pytest.mark.parametrize("limits", [(-2.0, 20.0), (20.0, -2.0)])
def test_the_curve_goes_to_the_typed_axis_limits(figure, data, limits) -> None:
    figure.axes[0].x.limits = limits
    figure.axes[0].artists[1].curve_to_limits = True
    xs = _curve(figure, data)
    assert (xs[0], xs[-1]) == (-2.0, 20.0)


def test_the_limits_of_a_panel_that_shares_x_count(figure: Figure, data) -> None:
    figure.layout.share_x = "col"
    figure.axes[1].x.limits = (-2.0, 20.0)
    figure.axes[0].artists[1].curve_to_limits = True
    xs = _curve(figure, data)
    assert (xs[0], xs[-1]) == (-2.0, 20.0)


def test_to_the_limits_waits_for_typed_ones(figure, data, columns) -> None:
    fit = figure.axes[0].artists[1]
    fit.curve_to_limits = True
    xs = _curve(figure, data)
    assert (xs[0], xs[-1]) == (columns["t"].min(), columns["t"].max())
    fit.curve_range = (1.0, 30.0)  # the range typed serves meanwhile
    xs = _curve(figure, data)
    assert (xs[0], xs[-1]) == (1.0, 30.0)


def test_typed_limits_win_over_a_typed_range(figure: Figure, data) -> None:
    fit = figure.axes[0].artists[1]
    fit.curve_range, fit.curve_to_limits = (1.0, 30.0), True
    figure.axes[0].x.limits = (0.0, 12.0)
    xs = _curve(figure, data)
    assert (xs[0], xs[-1]) == (0.0, 12.0)


def test_on_a_log_axis_a_given_range_is_sampled_in_log(figure, data) -> None:
    figure.axes[0].x.scale = "log"
    even = np.diff(_curve(figure, data))
    assert even == pytest.approx([even[0]] * len(even))  # as before
    figure.axes[0].artists[1].curve_range = (0.1, 100.0)
    figure.axes[0].artists[1].mark_extrapolated = False  # one plain curve
    ratios = np.diff(np.log(_curve(figure, data)))
    assert ratios == pytest.approx([ratios[0]] * len(ratios))


# --- beyond the data, another line (F1.9) ------------------------------------


def _drawn_x(line) -> np.ndarray:
    """The x of the samples a line really shows."""
    x, y = (np.asarray(v, dtype=float) for v in line.get_data())
    return x[np.isfinite(y)]


def _curve_lines(figure: Figure, data):
    fit = figure.axes[0].artists[1]
    return _lines(render(figure, data).axes[0], fit.id)


def test_the_curve_is_dashed_where_it_leaves_the_data(figure, data, columns) -> None:
    fit = figure.axes[0].artists[1]
    fit.linestyle, fit.label, fit.curve_range = "-", "fit", (-5.0, 25.0)
    measured, beyond = _curve_lines(figure, data)
    first, last = columns["t"].min(), columns["t"].max()
    assert (measured.get_linestyle(), beyond.get_linestyle()) == ("-", "--")
    assert measured.get_color() == beyond.get_color()
    assert measured.get_label() == "fit" and beyond.get_label() == "_nolegend_"
    inside, outside = _drawn_x(measured), _drawn_x(beyond)
    assert (inside.min(), inside.max()) == (first, last)  # no gap between them
    assert (outside.min(), outside.max()) == (-5.0, 25.0)
    assert not ((outside > first) & (outside < last)).any()
    assert {first, last} <= set(outside)


@pytest.mark.parametrize(
    "settings",
    [
        {},  # along the data
        {"curve_range": (2.0, 8.0)},  # given, but within them
        {"curve_range": (-5.0, 25.0), "mark_extrapolated": False},
        {
            "curve_range": (-5.0, 25.0),
            "mark_extrapolated": False,
            "extrapolated_color": "red",
        },
        {"curve_range": (-5.0, 25.0), "extrapolated_linestyle": "--"},  # as it is
        {"fit_range": (3.0, 7.0), "extend_curve": True},  # unfitted, but measured
    ],
)
def test_a_curve_drawn_alike_stays_one_line(figure, data, settings) -> None:
    fit = figure.axes[0].artists[1]  # dashed itself
    for name, value in settings.items():
        setattr(fit, name, value)
    assert len(_curve_lines(figure, data)) == 1


def test_a_curve_away_from_the_data_is_dashed_all_along(figure, data) -> None:
    fit = figure.axes[0].artists[1]
    fit.linestyle, fit.curve_range = "-", (20.0, 30.0)
    measured, beyond = _curve_lines(figure, data)
    assert _drawn_x(measured).size == 0
    assert (_drawn_x(beyond).min(), _drawn_x(beyond).max()) == (20.0, 30.0)


@pytest.mark.parametrize(
    ("settings", "look"),
    [
        ({"extrapolated_color": "red"}, ("--", "#ff0000", 1.5)),
        ({"extrapolated_linewidth": 0.5}, ("--", None, 0.5)),
        # In the curve's own style, set apart by color or width alone.
        (
            {
                "linestyle": "-",
                "extrapolated_linestyle": "-",
                "extrapolated_color": "k",
            },
            ("-", "#000000", 1.5),
        ),
        (
            {
                "linestyle": "-",
                "extrapolated_linestyle": "-",
                "extrapolated_linewidth": 3.0,
            },
            ("-", None, 3.0),
        ),
        ({"extrapolated_linestyle": ":"}, (":", None, 1.5)),
    ],
    ids=["color", "width", "color-alone", "width-alone", "dotted"],
)
def test_the_part_beyond_the_data_has_a_look_of_its_own(
    figure, data, settings, look
) -> None:
    fit = figure.axes[0].artists[1]
    fit.curve_range = (-5.0, 25.0)
    for name, value in settings.items():
        setattr(fit, name, value)
    measured, beyond = _curve_lines(figure, data)
    style, color, width = look
    assert beyond.get_linestyle() == style and beyond.get_linewidth() == width
    expected = color or measured.get_color()  # None: the curve's
    assert matplotlib.colors.to_hex(beyond.get_color()) == matplotlib.colors.to_hex(
        expected
    )
