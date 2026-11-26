"""Where a fitted curve begins and ends (F1.9): the model, and what the problem
list and the range of values make of it."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from figscribe.model import (
    Axes,
    AxisSpec,
    ColumnRef,
    CsvSource,
    Figure,
    FitCurve,
    FitResult,
    LinePlot,
    PredefinedFit,
    Project,
    dumps,
    loads,
    validate_references,
)
from figscribe.model.validate import axis_values

T = np.linspace(1.0, 10.0, 10)
SOURCE = CsvSource(path="run.csv", sha256="0" * 64, columns=["t", "U"])


def data(ref):
    return T if ref.column == "t" else 2.0 * T


def col(name: str) -> ColumnRef:
    return ColumnRef(source=SOURCE.id, column=name)


def _project(x: AxisSpec | None = None, **curve) -> Project:
    plot = LinePlot(x=col("t"), y=col("U"))
    fit = FitCurve(
        target=plot.id,
        model=PredefinedFit(name="linear"),
        result=FitResult(parameters={"a": 2.0, "b": 0.0}, uncertainties={}),
        **curve,
    )
    axes = Axes(x=x or AxisSpec(), artists=[plot, fit])
    return Project(sources=[SOURCE], figures=[Figure(axes=[axes])])


def _problems(project: Project) -> list[str]:
    return [str(issue) for issue in validate_references(project, data)]


def test_the_curve_ends_are_kept_in_the_file() -> None:
    project = _project(curve_range=(0.0, 20.0), curve_to_limits=True)
    fit = loads(dumps(project)).figures[0].axes[0].artists[1]
    assert (fit.curve_range, fit.curve_to_limits) == ((0.0, 20.0), True)


@pytest.mark.parametrize("ends", [(2.0, 2.0), (3.0, 1.0)])
def test_the_lower_end_is_below_the_upper(ends) -> None:
    with pytest.raises(ValidationError, match="curve"):
        _project(curve_range=ends)


def test_a_range_beyond_the_data_is_nothing_to_report() -> None:
    assert _problems(_project(curve_range=(0.0, 20.0))) == []


def test_a_range_away_from_the_data_is_reported() -> None:
    (problem,) = _problems(_project(curve_range=(20.0, 30.0)))
    assert "curve_range" in problem
    assert "from 20 to 30" in problem and "1 to 10" in problem


def test_to_the_limits_without_typed_limits_is_reported() -> None:
    (problem,) = _problems(_project(curve_to_limits=True))
    assert "curve_to_limits" in problem and "no range typed" in problem
    typed = AxisSpec(limits=(0.0, 20.0))
    assert _problems(_project(typed, curve_to_limits=True)) == []


@pytest.mark.parametrize(
    ("x", "curve"),
    [
        (AxisSpec(scale="log"), {"curve_range": (0.0, 20.0)}),
        (
            AxisSpec(scale="log", limits=(-1.0, 20.0)),
            {"curve_to_limits": True},
        ),
    ],
)
def test_a_curve_from_zero_on_a_log_axis_is_reported(x, curve) -> None:
    assert any("logarithmic" in p for p in _problems(_project(x, **curve)))


def test_a_curve_beyond_the_data_counts_among_the_values() -> None:
    """The breaks and the range of an automatic axis reason from what is drawn."""
    figure = _project(curve_range=(0.0, 20.0)).figures[0]
    x = axis_values(figure, 0, "x", data)
    y = axis_values(figure, 0, "y", data)
    assert (x.min(), x.max()) == (0.0, 20.0)
    assert (y.min(), y.max()) == (0.0, 40.0)
    plain = _project().figures[0]
    assert axis_values(plain, 0, "x", data).max() == 10.0
