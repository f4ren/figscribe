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
from figscribe.fit import FitError, add_fit, refit, set_left_out
from figscribe.io import load_data
from figscribe.io.csvfile import csv_source
from figscribe.model import (
    Annotation,
    Axes,
    AxisSpec,
    ColumnRef,
    Conversion,
    ErrorbarPlot,
    Figure,
    FitCurve,
    LinePlot,
    PredefinedFit,
    Project,
    Reduction,
    ReferenceLine,
    Smoothing,
    validate_references,
)
from figscribe.units import (
    default_smoothing,
    set_conversion,
    set_processing,
    set_range,
)

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


def test_normalised_to_the_maximum_with_its_errors(tmp_path: Path) -> None:
    _, data, plot = made(tmp_path, normalize="max")
    y = values(tmp_path)
    shown = plot_data(plot, data)
    np.testing.assert_array_equal(shown.y, y / y.max())
    np.testing.assert_array_equal(shown.yerr, np.full(20, 0.1) / y.max())


def test_normalised_to_the_area_after_smoothing(tmp_path: Path) -> None:
    how = Smoothing(method="moving", window=3)
    _, data, plot = made(tmp_path, smoothing=how, normalize="area", left_out=[4])
    used = X != 4
    y = values(tmp_path)
    y[used] = uniform_filter1d(y[used], 3, mode="nearest")
    area = np.trapezoid(y[used], X[used])
    shown = plot_data(plot, data)
    np.testing.assert_allclose(shown.y, y / area)
    assert np.trapezoid(shown.y[used], X[used]) == pytest.approx(1)


def test_nothing_above_zero_cannot_be_normalised(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path, y_conversion=Conversion(formula="x - 10"))
    with pytest.raises(FitError, match="above zero"):
        set_processing(project, plot.id, "normalize", "max", data)


def test_the_axis_follows_into_normalised_values_and_back(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path)
    panel = project.figures[0].axes[0]
    panel.y = AxisSpec(label="U", unit="V", limits=(0.0, 4.0))
    panel.artists.append(ReferenceLine(orientation="horizontal", at=2.0))
    top = values(tmp_path).max()
    set_processing(project, plot.id, "normalize", "max", data).apply(project)
    panel = project.figures[0].axes[0]
    assert panel.y.unit is None
    np.testing.assert_allclose(panel.y.limits, (0, 4 / top))
    np.testing.assert_allclose(panel.artists[1].at, 2 / top)
    set_processing(project, plot.id, "normalize", None, data).apply(project)
    panel = project.figures[0].axes[0]
    np.testing.assert_allclose(panel.y.limits, (0, 4))
    np.testing.assert_allclose(panel.artists[1].at, 2)


def test_normalising_fits_again_from_new_start_values(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path)
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    add_fit(project, fit).apply(project)
    refit(project, fit.id, data).apply(project)
    before = find(project, fit.id).result.parameters["b"]
    set_processing(project, plot.id, "normalize", "max", data).apply(project)
    after = find(project, fit.id).result.parameters["b"]
    assert after == pytest.approx(before / values(tmp_path).max())


def test_a_unit_of_normalised_values_leaves_their_axis(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path, normalize="max")
    panel = project.figures[0].axes[0]
    panel.y = AxisSpec(label="U", limits=(0.0, 1.2))
    panel.artists.append(ReferenceLine(orientation="horizontal", at=0.5))
    mv = Conversion(factor=1000.0, unit="mV")
    set_conversion(project, plot.id, "y", mv, data).apply(project)
    panel = project.figures[0].axes[0]
    assert (panel.y.unit, panel.y.limits, panel.artists[1].at) == (None, (0, 1.2), 0.5)


def test_a_missing_or_changed_file_still_lists_problems(tmp_path: Path) -> None:
    project, _, _ = made(tmp_path, smoothing=Smoothing(), normalize="max")
    for change in ("changed", "missing"):
        if change == "changed":
            (tmp_path / "d.csv").write_text("x,y,dy\n1,2,3\n")
        else:
            (tmp_path / "d.csv").unlink()
        validate_references(project, load_data(project, tmp_path))  # no crash


def test_removing_a_setting_is_never_refused(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path)
    # Neither can be computed, as after a new version of the file.
    plot.smoothing = Smoothing(window=21)
    plot.normalize = "max"
    plot.y_conversion = Conversion(formula="x - 10")
    set_processing(project, plot.id, "normalize", None, data).apply(project)
    set_processing(project, plot.id, "smoothing", None, data).apply(project)
    assert project.figures[0].axes[0].artists[0].smoothing is None


@pytest.mark.parametrize("change", ["range", "left out", "unit"])
def test_what_would_stop_a_plot_being_computed_is_refused(tmp_path, change) -> None:
    project, data, plot = made(tmp_path, smoothing=Smoothing(), normalize="max")
    with pytest.raises(FitError, match="points|above zero"):
        if change == "range":
            set_range(project, plot.id, (0.0, 4.0), data)
        elif change == "left out":
            set_left_out(project, plot.id, list(range(12)), data)
        else:
            below = Conversion(formula="x - 10")
            set_conversion(project, plot.id, "y", below, data)


@pytest.mark.parametrize(
    ("axis", "conversion"),
    [
        ("x", Conversion(factor=1 / 60, unit="min")),
        ("y", Conversion(formula="x * 2 - 1")),
    ],
    ids=["an area over another x", "an offset in y"],
)
def test_limits_follow_normalised_values_that_change(
    tmp_path: Path, axis: str, conversion: Conversion
) -> None:
    how = "area" if axis == "x" else "max"
    project, data, plot = made(tmp_path, normalize=how)
    panel = project.figures[0].axes[0]
    panel.x = AxisSpec(limits=(0.0, 19.0))
    before = plot_data(plot, data).y
    panel.y = AxisSpec(limits=(float(before.min()), float(before.max())))
    note = Annotation(text="n", position=(10.0, float(before.max())))
    panel.artists.append(note)
    set_conversion(project, plot.id, axis, conversion, data).apply(project)
    panel = project.figures[0].axes[0]
    after = plot_data(panel.artists[0], data).y
    np.testing.assert_allclose(panel.y.limits, (after.min(), after.max()))
    assert panel.artists[1].position[1] == pytest.approx(after.max())
    if axis == "x":
        assert panel.artists[1].position[0] == pytest.approx(10 / 60)
        np.testing.assert_allclose(panel.x.limits, (0, 19 / 60))


@pytest.mark.parametrize(("rows", "window", "order"), [(8, 7, 3), (3, 3, 2)])
def test_smoothing_starts_with_a_window_that_fits(tmp_path, rows, window, order):
    _, data, plot = made(tmp_path, left_out=list(range(rows, 20)))
    assert default_smoothing(plot, data) == Smoothing(window=window, order=order)


def test_too_few_points_to_smooth(tmp_path: Path) -> None:
    _, data, plot = made(tmp_path, left_out=list(range(2, 20)))
    with pytest.raises(FitError, match="at least 3"):
        default_smoothing(plot, data)


def test_smoothed_values_a_log_axis_cannot_show_are_listed(tmp_path: Path) -> None:
    project, data, plot = made(tmp_path, y_conversion=Conversion(formula="x - 2"))
    plot.y_conversion = None
    plot.smoothing = Smoothing(window=19, order=0)
    project.figures[0].axes[0].y = AxisSpec(scale="log")
    plain = [i.message for i in validate_references(project, data)]
    assert plain == []
    spike = "x,y,dy\n" + "".join(
        f"{i},{100 if i == 9 else 0.001},0.1\n" for i in range(20)
    )
    (tmp_path / "d.csv").write_text(spike)
    source = csv_source(tmp_path / "d.csv", tmp_path)
    project.sources = [source.model_copy(update={"id": project.sources[0].id})]
    plot.smoothing = Smoothing(window=7, order=2)
    data = load_data(project, tmp_path)
    problems = [i.message for i in validate_references(project, data)]
    assert any("zero or below" in p for p in problems)
