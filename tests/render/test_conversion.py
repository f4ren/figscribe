"""Units and a range per plot in the renderer and the fits (decision 0041)."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.fit import refit
from figscribe.model import (
    AllanDeviationPlot,
    Axes,
    ColumnRef,
    Conversion,
    CsvSource,
    ErrorbarPlot,
    Figure,
    FitCurve,
    Histogram,
    LinePlot,
    PredefinedFit,
    Project,
)
from figscribe.render import render

HOURS = Conversion(factor=1 / 3600, from_start=True, unit="h")
SOURCE = CsvSource(path="run.csv", sha256="0" * 64, columns=["t", "U", "dU"])
T = 1.7e9 + 360.0 * np.arange(41)  # timestamps in s, every 6 min for 4 h
COLUMNS = {
    "t": T,
    "U": np.exp(-(((T - T[20]) / 3600) ** 2)),
    "dU": np.full(41, 0.05),
}


def data(ref: ColumnRef) -> np.ndarray:
    return COLUMNS[ref.column]


def col(name: str) -> ColumnRef:
    return ColumnRef(source=SOURCE.id, column=name)


def _ax(*artists):
    return render(Figure(axes=[Axes(artists=list(artists))]), data).axes[0]


def test_points_are_drawn_converted_and_only_within_their_range() -> None:
    plot = ErrorbarPlot(
        x=col("t"),
        y=col("U"),
        yerr=col("dU"),
        x_conversion=HOURS,
        y_conversion=Conversion(factor=1000.0, unit="mV"),
        x_range=(1.0, 3.0),
        left_out=[2, 15],  # row 2 lies outside the range, row 15 within
    )
    ax = _ax(plot)
    line = ax.containers[0].lines[0]
    hours = (T - T[0]) / 3600
    np.testing.assert_allclose(line.get_xdata(), hours)
    y = line.get_ydata()
    inside = (hours >= 1.0) & (hours <= 3.0)
    shown = inside.copy()
    shown[15] = False
    np.testing.assert_allclose(y[shown], 1000 * COLUMNS["U"][shown])
    assert np.isnan(y[~shown]).all()
    low, high = ax.get_xlim()
    assert 0.8 < low and high < 3.2  # rows outside the range set no limits
    apart = ax.containers[1].lines[0]  # the left-out rows drawn apart
    assert list(apart.get_xdata()) == [hours[15]]  # row 2 is not drawn at all


def test_a_histogram_counts_converted_values_within_its_range() -> None:
    plot = Histogram(
        values=col("U"),
        bins=4,
        x_conversion=Conversion(factor=1000.0, unit="mV"),
        x_range=(200.0, 1000.0),
    )
    ax = _ax(plot)
    edges = [patch.get_x() for patch in ax.patches]
    assert edges[0] == pytest.approx(200.0)
    right = ax.patches[-1].get_x() + ax.patches[-1].get_width()
    assert right == pytest.approx(1000.0)  # the bins span the range
    kept = (1000 * COLUMNS["U"] >= 200) & (1000 * COLUMNS["U"] <= 1000)
    assert sum(p.get_height() for p in ax.patches) == kept.sum()


def test_an_allan_deviation_shows_tau_converted_over_its_range() -> None:
    rng = np.random.default_rng(3)
    COLUMNS["y"] = rng.normal(size=41)
    plot = AllanDeviationPlot(
        values=col("y"),
        time=col("t"),
        x_conversion=Conversion(factor=1 / 3600, unit="h"),
        x_range=(0.0, 2.0),  # the first 21 samples: 0 to 2 h after the first
    )
    line = _ax(plot).containers[0].lines[0]
    m = np.array([1, 2, 4, 8])  # up to (22 - 1) // 2 phase points
    np.testing.assert_allclose(line.get_xdata(), m * 360.0 / 3600)


def test_a_fit_fits_the_converted_rows_within_the_range() -> None:
    COLUMNS["line"] = 2.0 * T  # 2 V per s
    plot = LinePlot(x=col("t"), y=col("line"), x_conversion=HOURS, x_range=(1, 3))
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    project = Project(
        sources=[SOURCE], figures=[Figure(axes=[Axes(artists=[plot, fit])])]
    )
    refit(project, fit.id, data).apply(project)
    assert fit.result.parameters["a"] == pytest.approx(7200.0)  # V per h, as shown
    curve = render(project.figures[0], data).axes[0].lines[-1]
    assert curve.get_xdata().min() == pytest.approx(1.0)
    assert curve.get_xdata().max() == pytest.approx(3.0)
