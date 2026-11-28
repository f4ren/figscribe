"""Date axes in the figure (decision 0082)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import date2num

from figscribe.io import load_data
from figscribe.model import (
    AxisSpec,
    Conversion,
    ErrorbarPlot,
    FunctionPlot,
    Histogram,
    LinePlot,
    Reduction,
    ReferenceLine,
)
from figscribe.model.timeaxes import not_on_dates, time_columns_of
from figscribe.render import render
from tests.timedata import project_of

HOUR = Conversion(factor=1 / 3600, from_start=True, unit="h")


def line(**kwargs):
    return lambda ref: LinePlot(x=ref("time"), y=ref("T"), **kwargs)


def _drawn(project, folder: Path):
    figure = render(project.figures[0], load_data(project, folder))
    FigureCanvasAgg(figure).draw()
    return figure


def _labels(axis) -> list[str]:
    return [label.get_text() for label in axis.get_ticklabels()]


def _day(text: str) -> float:
    return float(date2num(np.datetime64(text)))


def test_a_column_of_times_gives_a_date_axis(tmp_path: Path) -> None:
    project, _ = project_of(tmp_path, line())
    (ax,) = _drawn(project, tmp_path).axes
    (drawn,) = ax.lines
    assert drawn.get_xdata()[0] == _day("2026-11-01T22:00")
    # Numbers only, with the day at midnight and beside the axis.
    assert "11-02" in _labels(ax.xaxis) and "22:00" in _labels(ax.xaxis)
    assert ax.xaxis.get_offset_text().get_text().startswith("2026-11")


def test_typed_limits_are_days_since_1970(tmp_path: Path) -> None:
    ends = (_day("2026-11-01T23:00"), _day("2026-11-02T00:00"))
    project, _ = project_of(tmp_path, line(), x=AxisSpec(limits=ends, scale="log"))
    (ax,) = _drawn(project, tmp_path).axes
    assert ax.get_xlim() == ends
    assert ax.get_xscale() == "linear"  # a date axis has no logarithm


def test_since_the_start_is_a_number_axis(tmp_path: Path) -> None:
    project, _ = project_of(tmp_path, line(x_conversion=HOUR))
    (ax,) = _drawn(project, tmp_path).axes
    np.testing.assert_allclose(ax.lines[0].get_xdata()[:3], [0, 1 / 6, 1 / 3])
    assert "11-02" not in _labels(ax.xaxis)


def test_a_conversion_counts_from_the_start_unasked(tmp_path: Path) -> None:
    seconds = Conversion(factor=1.0, from_start=False, unit="s")
    project, _ = project_of(tmp_path, line(x_conversion=seconds))
    (ax,) = _drawn(project, tmp_path).axes
    np.testing.assert_array_equal(ax.lines[0].get_xdata()[:3], [0, 600, 1200])


def test_a_range_of_a_plot_over_dates(tmp_path: Path) -> None:
    ends = (_day("2026-11-01T22:20"), _day("2026-11-01T22:40"))
    project, _ = project_of(tmp_path, line(x_range=ends))
    (ax,) = _drawn(project, tmp_path).axes
    assert np.count_nonzero(np.isfinite(ax.lines[0].get_ydata())) == 3


def test_dates_on_the_y_axis(tmp_path: Path) -> None:
    project, _ = project_of(tmp_path, lambda ref: LinePlot(x=ref("T"), y=ref("time")))
    (ax,) = _drawn(project, tmp_path).axes
    assert ax.yaxis.get_offset_text().get_text().startswith("2026-11")


NOT_DRAWN = {
    "numbers on a date axis": (
        lambda ref: LinePlot(x=ref("p"), y=ref("T")),
        "its x are numbers",
    ),
    "x errors": (
        lambda ref: ErrorbarPlot(x=ref("time"), y=ref("T"), xerr=ref("dT")),
        "dates cannot have x errors",
    ),
    "errors that are dates": (
        lambda ref: ErrorbarPlot(x=ref("time"), y=ref("T"), yerr=ref("time")),
        "are dates, not durations",
    ),
    "fewer points": (
        line(reduction=Reduction(count=3)),
        "fewer points",
    ),
    "histogram of dates": (
        lambda ref: Histogram(values=ref("time")),
        "cannot count dates",
    ),
    "histogram of numbers": (
        lambda ref: Histogram(values=ref("T")),
        "numbers on a date axis",
    ),
    "function": (lambda ref: FunctionPlot(expression="x"), "function"),
}


@pytest.mark.parametrize("case", NOT_DRAWN)
def test_what_is_not_drawn_on_a_date_axis(tmp_path: Path, case: str) -> None:
    make, why = NOT_DRAWN[case]
    project, _ = project_of(tmp_path, line(), make)
    other = project.figures[0].axes[0].artists[1]
    found = not_on_dates(project.figures[0], 0, other, time_columns_of(project))
    assert why in found
    (ax,) = _drawn(project, tmp_path).axes
    gids = {a.get_gid() for a in ax.get_children()}
    assert other.id not in gids


def test_reference_lines_stay(tmp_path: Path) -> None:
    def mark(ref):
        return ReferenceLine(orientation="vertical", at=_day("2026-11-02"))

    project, _ = project_of(tmp_path, line(), mark)
    (ax,) = _drawn(project, tmp_path).axes
    assert len(ax.lines) == 2
