"""Smoothing and normalising the values of a plot (decision 0083)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from scipy.ndimage import uniform_filter1d
from scipy.signal import savgol_filter

from figscribe.commands import find
from figscribe.convert import plot_data
from figscribe.fit import FitError, add_fit, refit
from figscribe.io import load_data
from figscribe.io.csvfile import csv_source
from figscribe.model import (
    Axes,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    FitCurve,
    LinePlot,
    PredefinedFit,
    Project,
    Reduction,
    Smoothing,
    validate_references,
)
from figscribe.units import set_processing

X = np.arange(20.0)
Y = np.sin(X / 2) + 2 + 0.1 * (-1) ** X


def made(folder: Path, **plot):
    """(project, data, plot) of a line over x and y with an error dy."""
    rows = "\n".join(f"{a:g},{b:.6f},0.1" for a, b in zip(X, Y, strict=True))
    (folder / "d.csv").write_text(f"x,y,dy\n{rows}\n")
    source = csv_source(folder / "d.csv", folder)

    def ref(name: str) -> ColumnRef:
        return ColumnRef(source=source.id, column=name)

    line = ErrorbarPlot(x=ref("x"), y=ref("y"), yerr=ref("dy"), **plot)
    project = Project(sources=[source], figures=[Figure(axes=[Axes(artists=[line])])])
    return project, load_data(project, folder), line


def values(folder: Path) -> np.ndarray:
    return np.loadtxt(folder / "d.csv", delimiter=",", skiprows=1, usecols=1)


@pytest.mark.parametrize("window", [2, 4, 10])
def test_a_window_is_odd_and_at_least_three(window: int) -> None:
    with pytest.raises(ValidationError):
        Smoothing(window=window)


def test_savitzky_golay_needs_a_window_above_its_order() -> None:
    with pytest.raises(ValidationError):
        Smoothing(window=3, order=3)
    Smoothing(method="moving", window=3, order=3)  # which has no order


def test_savitzky_golay(tmp_path: Path) -> None:
    _, data, plot = made(tmp_path, smoothing=Smoothing(window=7, order=2))
    shown = plot_data(plot, data)
    np.testing.assert_array_equal(shown.y, savgol_filter(values(tmp_path), 7, 2))
    np.testing.assert_array_equal(shown.yerr, np.full(20, 0.1))


def test_a_moving_average(tmp_path: Path) -> None:
    how = Smoothing(method="moving", window=5)
    _, data, plot = made(tmp_path, smoothing=how)
    expected = uniform_filter1d(values(tmp_path), 5, mode="nearest")
    np.testing.assert_array_equal(plot_data(plot, data).y, expected)


def test_left_out_rows_and_rows_outside_the_range_take_no_part(tmp_path) -> None:
    how = Smoothing(method="moving", window=3)
    _, data, plot = made(tmp_path, smoothing=how, left_out=[4], x_range=(2.0, 15.0))
    y = values(tmp_path)
    used = (X >= 2) & (X <= 15) & (X != 4)
    expected = y.copy()
    expected[used] = uniform_filter1d(y[used], 3, mode="nearest")
    np.testing.assert_array_equal(plot_data(plot, data).y, expected)


def test_smoothing_comes_before_fewer_points(tmp_path: Path) -> None:
    how = Smoothing(method="moving", window=3)
    _, data, plot = made(tmp_path, smoothing=how, reduction=Reduction(count=5))
    smooth = uniform_filter1d(values(tmp_path), 3, mode="nearest")
    np.testing.assert_allclose(
        plot_data(plot, data).y, smooth.reshape(4, 5).mean(axis=1)
    )


def test_a_window_longer_than_the_data_is_refused(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path)
    with pytest.raises(FitError, match="21 points.*20"):
        set_processing(project, plot.id, "smoothing", Smoothing(window=21), data)
    plot.smoothing = Smoothing(window=21)  # as a new version of the file may
    problems = [i.message for i in validate_references(project, data)]
    assert any("21 points" in p for p in problems)


def test_smoothing_fits_again_and_says_what_that_is_worth(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path)
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    add_fit(project, fit).apply(project)
    refit(project, fit.id, data).apply(project)
    before = find(project, fit.id).result.parameters["a"]
    how = Smoothing(method="moving", window=7)
    set_processing(project, plot.id, "smoothing", how, data).apply(project)
    assert find(project, fit.id).result.parameters["a"] != before
    problems = [i.message for i in validate_references(project, data)]
    assert any("fits smoothed data" in p for p in problems)


def test_a_line_plot_is_smoothed_too(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path)
    line = LinePlot(x=plot.x, y=plot.y, smoothing=Smoothing())
    assert not np.array_equal(plot_data(line, data).y, values(tmp_path))
