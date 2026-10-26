"""The Allan deviation (roadmap F4.9): the computation against published
values, and the plot in the renderer and the problem list."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.allan import (
    averaging_factors,
    overlapping_adev,
    phase_of,
    sample_interval,
)
from figscribe.io import DataError
from figscribe.model import (
    AllanDeviationPlot,
    Axes,
    ColumnRef,
    CsvSource,
    Figure,
    Project,
    validate_references,
)
from figscribe.render import render


def nist_1000_points() -> np.ndarray:
    """The test series of NIST SP 1065, section 12.4: a linear congruential
    generator from 1234567890, as fractional frequency."""
    n, values = 1234567890, []
    for _ in range(1000):
        values.append(n / 2147483647)
        n = (16807 * n) % 2147483647
    return np.array(values)


def test_the_nist_test_series_gives_its_published_values() -> None:
    y = nist_1000_points()
    assert y.mean() == pytest.approx(0.4897745, abs=5e-8)  # as published
    sigma = overlapping_adev(phase_of(y, "frequency", 1.0), 1.0, np.array([1, 10]))
    np.testing.assert_allclose(sigma, [2.922319e-01, 9.159953e-02], rtol=2e-7)


def test_white_frequency_noise_falls_as_one_over_root_tau() -> None:
    y = np.random.default_rng(2).normal(scale=3e-12, size=200_000)
    m = np.array([1, 4, 16, 64])
    sigma = overlapping_adev(phase_of(y, "frequency", 0.5), 0.5, m)
    # σ_y(τ) = σ · √(τ0 / τ) for white frequency noise of standard deviation σ
    np.testing.assert_allclose(sigma * np.sqrt(m), 3e-12, rtol=0.05)


def test_phase_and_frequency_give_the_same_curve() -> None:
    y = np.random.default_rng(3).normal(size=500)
    tau0 = 0.25
    phase = phase_of(y, "frequency", tau0)
    m = averaging_factors(phase.size, "octave")
    np.testing.assert_allclose(
        overlapping_adev(phase, tau0, m),
        overlapping_adev(phase_of(phase, "phase", tau0), tau0, m),
    )


@pytest.mark.parametrize(
    ("taus", "expected"),
    [
        ("octave", [1, 2, 4, 8, 16]),
        ("decade", [1, 2, 5, 10, 20]),
        ("all", list(range(1, 21))),
    ],
)
def test_averaging_factors_reach_half_the_series(taus, expected) -> None:
    assert list(averaging_factors(41, taus)) == expected  # 41 phase points: m ≤ 20


def test_too_short_a_series_has_no_factors() -> None:
    assert averaging_factors(2, "octave").size == 0


def test_the_sample_interval_comes_from_even_times() -> None:
    assert sample_interval([0.0, 0.5, 1.0, 1.5]) == 0.5
    with pytest.raises(DataError, match="not evenly spaced"):
        sample_interval([0.0, 0.5, 1.0, 2.0])
    with pytest.raises(DataError, match="do not increase"):
        sample_interval([3.0, 2.0, 1.0])


# --- the plot ----------------------------------------------------------------

SOURCE = CsvSource(path="clock.csv", sha256="0" * 64, columns=["t", "y", "x"])
SERIES = np.random.default_rng(4).normal(scale=1e-11, size=64)
COLUMNS = {
    "t": np.arange(64) * 0.5,
    "y": SERIES,
    "x": phase_of(SERIES, "frequency", 0.5),
    "uneven": np.r_[np.arange(63) * 0.5, 40.0],
    "gap": np.r_[SERIES[:10], np.nan, SERIES[11:]],
}


def _data(ref):
    return COLUMNS[ref.column]


def col(name: str) -> ColumnRef:
    return ColumnRef(source=SOURCE.id, column=name)


def _drawn(plot: AllanDeviationPlot):
    figure = render(Figure(axes=[Axes(artists=[plot])]), _data)
    return figure.axes[0]


def test_the_plot_shows_sigma_against_tau() -> None:
    ax = _drawn(AllanDeviationPlot(values=col("y"), sample_interval=0.5))
    (container,) = ax.containers
    line = container.lines[0]
    m = averaging_factors(65, "octave")
    np.testing.assert_allclose(line.get_xdata(), m * 0.5)
    expected = overlapping_adev(phase_of(SERIES, "frequency", 0.5), 0.5, m)
    np.testing.assert_allclose(line.get_ydata(), expected)
    assert container.has_yerr


def test_a_time_column_or_phase_data_draw_the_same() -> None:
    by_rate = _drawn(AllanDeviationPlot(values=col("y"), sample_interval=0.5))
    by_time = _drawn(AllanDeviationPlot(values=col("y"), time=col("t")))
    by_phase = _drawn(
        AllanDeviationPlot(values=col("x"), data_type="phase", sample_interval=0.5)
    )
    first = by_rate.containers[0].lines[0].get_ydata()
    for other in (by_time, by_phase):
        np.testing.assert_allclose(other.containers[0].lines[0].get_ydata(), first)


def test_uneven_times_are_refused_in_words() -> None:
    with pytest.raises(DataError, match="not evenly spaced"):
        _drawn(AllanDeviationPlot(values=col("y"), time=col("uneven")))


def test_a_series_with_a_gap_is_not_drawn_and_said_so() -> None:
    plot = AllanDeviationPlot(values=col("gap"))
    assert not _drawn(plot).containers
    project = Project(sources=[SOURCE], figures=[Figure(axes=[Axes(artists=[plot])])])
    issues = [str(issue) for issue in validate_references(project, _data)]
    assert any("unbroken series" in issue for issue in issues), issues
