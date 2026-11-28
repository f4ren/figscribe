"""Date axes: what is listed as a problem, fits, and switching between dates
and the time since the start (decision 0082)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from matplotlib.dates import date2num

from figscribe.commands import find
from figscribe.fit import FitError, add_fit, refit
from figscribe.io import load_data
from figscribe.model import (
    Annotation,
    ArrayRef,
    AxisSpec,
    Conversion,
    FitCurve,
    Histogram,
    ImagePlot,
    LinePlot,
    PredefinedFit,
    ReferenceLine,
    validate_references,
)
from figscribe.units import set_conversion, set_range
from tests.timedata import project_of

HOUR = Conversion(factor=1 / 3600, from_start=True, unit="h")
MINUTE = Conversion(factor=1 / 60, from_start=True, unit="min")


def _day(text: str) -> float:
    return float(date2num(np.datetime64(text)))


def line(**kwargs):
    return lambda ref: LinePlot(x=ref("time"), y=ref("T"), **kwargs)


def _problems(project, folder: Path) -> list[str]:
    data = load_data(project, folder)
    return [issue.message for issue in validate_references(project, data)]


def test_a_plain_date_plot_has_no_problem(tmp_path: Path) -> None:
    project, _ = project_of(tmp_path, line())
    assert _problems(project, tmp_path) == []


def test_what_is_not_drawn_is_listed(tmp_path: Path) -> None:
    project, _ = project_of(
        tmp_path,
        line(),
        lambda ref: Histogram(values=ref("time")),
        x=AxisSpec(scale="log", breaks=[(20760.0, 20760.1)]),
    )
    found = _problems(project, tmp_path)
    assert any("is not drawn: a histogram cannot count dates" in p for p in found)
    assert any("x axis shows dates" in p and "logarithmic" in p for p in found)
    assert any("x axis shows dates" in p and "breaks" in p for p in found)


def test_an_image_from_a_file_with_dates_is_listed(tmp_path: Path) -> None:
    def image(ref):
        return ImagePlot(data=ArrayRef(source=ref("T").source))

    project, _ = project_of(tmp_path, image)
    assert any("holds dates" in p for p in _problems(project, tmp_path))


def test_there_is_no_fit_to_dates(tmp_path: Path) -> None:
    project, _ = project_of(tmp_path, line())
    target = project.figures[0].axes[0].artists[0]
    fit = FitCurve(target=target.id, model=PredefinedFit(name="linear"))
    with pytest.raises(FitError, match="dates.*time since the start"):
        add_fit(project, fit).apply(project)
        refit(project, fit.id, load_data(project, tmp_path)).apply(project)


def test_switching_between_dates_and_the_time_since_the_start(tmp_path: Path) -> None:
    project, _ = project_of(
        tmp_path,
        line(x_range=(_day("2026-11-01T23:00"), _day("2026-11-02T01:00"))),
        lambda ref: ReferenceLine(orientation="vertical", at=_day("2026-11-02")),
        lambda ref: Annotation(text="n", position=(_day("2026-11-02T00:30"), 20.0)),
        x=AxisSpec(limits=(_day("2026-11-01T22:00"), _day("2026-11-02T02:00"))),
    )
    data = load_data(project, tmp_path)
    plot, mark, note = project.figures[0].axes[0].artists

    set_conversion(project, plot.id, "x", HOUR, data).apply(project)
    panel = project.figures[0].axes[0]
    np.testing.assert_allclose(panel.x.limits, (0, 4), atol=1e-6)
    assert panel.x.unit == "h"
    np.testing.assert_allclose(find(project, plot.id).x_range, (1, 3), atol=1e-6)
    np.testing.assert_allclose(find(project, mark.id).at, 2, atol=1e-6)
    np.testing.assert_allclose(find(project, note.id).position[0], 2.5, atol=1e-6)
    assert _problems(project, tmp_path) == []

    set_conversion(project, plot.id, "x", MINUTE, data).apply(project)
    np.testing.assert_allclose(find(project, mark.id).at, 120, atol=1e-6)

    set_conversion(project, plot.id, "x", None, data).apply(project)
    panel = project.figures[0].axes[0]
    np.testing.assert_allclose(find(project, mark.id).at, _day("2026-11-02"))
    np.testing.assert_allclose(
        panel.x.limits, (_day("2026-11-01T22:00"), _day("2026-11-02T02:00"))
    )
    assert panel.x.unit is None


def test_back_to_dates_leaves_a_fit_not_fitted(tmp_path: Path) -> None:
    project, _ = project_of(tmp_path, line(x_conversion=HOUR))
    plot = project.figures[0].axes[0].artists[0]
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    add_fit(project, fit).apply(project)
    data = load_data(project, tmp_path)
    refit(project, fit.id, data).apply(project)
    set_conversion(project, plot.id, "x", None, data).apply(project)
    assert find(project, fit.id).result is None
    assert any("there is no fit to dates" in p for p in _problems(project, tmp_path))
    set_conversion(project, plot.id, "x", HOUR, data).apply(project)
    refit(project, fit.id, data).apply(project)
    assert find(project, fit.id).result is not None


def test_a_range_of_dates_is_named_as_dates(tmp_path: Path) -> None:
    project, _ = project_of(tmp_path, line())
    plot = project.figures[0].axes[0].artists[0]
    ends = (_day("2026-11-01T23:00"), _day("2026-11-02"))
    command = set_range(project, plot.id, ends, load_data(project, tmp_path))
    assert command.description == "Use only x from 2026-11-01T23:00 to 2026-11-02"
