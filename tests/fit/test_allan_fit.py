"""Fitting an Allan deviation (roadmap F14, decision 0064): its points are the
ones the plot draws, so a fit, its residuals and the script share them."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from figscribe.convert import plot_data
from figscribe.fit import FitError, add_fit, refit
from figscribe.io import csv_source, load_data
from figscribe.model import (
    AllanDeviationPlot,
    Axes,
    ColumnRef,
    Conversion,
    ExpressionFit,
    Figure,
    FitCurve,
    Project,
)

SIGMA = 2e-12


@pytest.fixture
def clock(tmp_path: Path):
    """White frequency noise: σ_y(τ) = σ / √(τ / τ0)."""
    rng = np.random.default_rng(3)
    y = rng.normal(scale=SIGMA, size=2000)
    rows = "\n".join(f"{i * 0.5!r},{float(v)!r}" for i, v in enumerate(y))
    (tmp_path / "clock.csv").write_text(f"t,y\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "clock.csv", tmp_path, header_row=0)
    col = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    return source, col, tmp_path


def _project(source, plot) -> Project:
    return Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(axes=[Axes(artists=[plot])])],
    )


WHITE = ExpressionFit(expression="a / sqrt(x)", parameters=["a"])


def test_the_points_to_fit_are_the_points_drawn(clock) -> None:
    from figscribe.allan import allan_points

    source, col, folder = clock
    plot = AllanDeviationPlot(values=col["y"], time=col["t"])
    data = load_data(_project(source, plot), folder)
    shown = plot_data(plot, data)
    tau, sigma, error = allan_points(plot, data)
    assert np.array_equal(shown.x, tau) and np.array_equal(shown.y, sigma)
    assert np.array_equal(shown.yerr, error)
    assert shown.reduced and shown.used.all()


def test_white_noise_is_fitted_by_one_over_root_tau(clock) -> None:
    source, col, folder = clock
    plot = AllanDeviationPlot(values=col["y"], time=col["t"], error_bars=True)
    project = _project(source, plot)
    fit = FitCurve(target=plot.id, model=WHITE, initial_values={"a": 1e-12})
    add_fit(project, fit, residuals=True).apply(project)
    placed = next(a for a in project.figures[0].axes[0].artists if a.id == fit.id)
    refit(project, placed.id, load_data(project, folder)).apply(project)
    placed = next(a for a in project.figures[0].axes[0].artists if a.id == fit.id)
    a = placed.result.parameters["a"]
    # σ per sample 2e-12, one sample every 0.5 s: σ_y(τ) = σ √(τ0 / τ)
    assert a == pytest.approx(SIGMA * np.sqrt(0.5), rel=0.15)


def test_a_conversion_and_a_range_are_followed(clock) -> None:
    source, col, folder = clock
    minutes = Conversion(factor=1 / 60, unit="min")
    plot = AllanDeviationPlot(values=col["y"], time=col["t"], x_conversion=minutes)
    project = _project(source, plot)
    fit = FitCurve(
        target=plot.id,
        model=WHITE,
        initial_values={"a": 1e-12},
        fit_range=(0.05, 2.0),
    )
    add_fit(project, fit).apply(project)
    placed = next(a for a in project.figures[0].axes[0].artists if a.id == fit.id)
    data = load_data(project, folder)
    shown = plot_data(plot, data)
    assert shown.x.max() < 20  # τ in minutes, not seconds
    refit(project, placed.id, data).apply(project)
    placed = next(a for a in project.figures[0].axes[0].artists if a.id == fit.id)
    assert placed.result is not None
    from figscribe.fit import fitted_points

    used = fitted_points(shown, (), placed.fit_range)
    assert 0 < used.sum() < len(shown.x)
    assert shown.x[used].min() >= 0.05 and shown.x[used].max() <= 2.0


def test_a_series_with_gaps_has_nothing_to_fit(clock) -> None:
    source, col, folder = clock
    plot = AllanDeviationPlot(values=col["y"], time=col["t"])
    project = _project(source, plot)
    fit = FitCurve(target=plot.id, model=WHITE, initial_values={"a": 1e-12})
    add_fit(project, fit).apply(project)
    data = load_data(project, folder)

    def gappy(ref):
        values = np.array(data(ref), dtype=float)
        if ref.column == "y":
            values[10] = np.nan
        return values

    with pytest.raises(FitError):
        refit(project, fit.id, gappy)
