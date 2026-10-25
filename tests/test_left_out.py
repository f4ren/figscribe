"""Leaving points of a plot out (roadmap task F2): stored as rows on the plot,
drawn in a color of their own, skipped by every fit of the plot."""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.colors import to_rgb

from figscribe.commands import History
from figscribe.fit import FitError, evaluate, refit, set_left_out
from figscribe.model import (
    Axes,
    ColumnRef,
    CsvSource,
    ErrorbarPlot,
    Figure,
    FitCurve,
    LinePlot,
    PredefinedFit,
    Project,
    ScatterPlot,
    dumps,
    validate_references,
)
from figscribe.render import render

T = np.linspace(0.0, 9.0, 10)
U = 2.0 * T + 1.0
U[4] = 40.0  # a glitch


def _data(ref: ColumnRef) -> np.ndarray:
    return {"t": T, "U": U, "dU": np.full(T.size, 0.1)}[ref.column]


def _project(plot_type=ErrorbarPlot, **options) -> Project:
    source = CsvSource(path="scan.csv", sha256="0" * 64, columns=["t", "U", "dU"])
    ref = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    extra = {"yerr": ref["dU"]} if plot_type is ErrorbarPlot else {}
    plot = plot_type(x=ref["t"], y=ref["U"], **extra, **options)
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    figure = Figure(axes=[Axes(artists=[plot, fit])])
    return Project(sources=[source], figures=[figure])


def _plot(project: Project):
    return project.figures[0].axes[0].artists[0]


def _fit(project: Project) -> FitCurve:
    return project.figures[0].axes[0].artists[1]


def _drawn(figure, gid):
    ax = figure.axes[0]
    return [a for a in [*ax.lines, *ax.collections] if a.get_gid() == gid]


@pytest.mark.parametrize("plot_type", [LinePlot, ScatterPlot, ErrorbarPlot])
def test_left_out_points_are_drawn_apart_in_light_grey(plot_type) -> None:
    project = _project(plot_type, left_out=[4])
    drawn = render(project.figures[0], _data)
    kept, out = (a for a in _drawn(drawn, _plot(project).id) if hasattr(a, "rows"))
    assert list(kept.rows) == [0, 1, 2, 3, 5, 6, 7, 8, 9]
    assert list(out.rows) == [4]
    color = out.get_color() if hasattr(out, "get_color") else out.get_facecolor()[0]
    assert np.allclose(to_rgb(color), 0.7)  # light grey


def test_a_left_out_point_can_have_a_color_and_marker_of_its_own() -> None:
    project = _project(
        LinePlot, left_out=[4], left_out_color="red", left_out_marker="x"
    )
    drawn = render(project.figures[0], _data)
    out = next(a for a in _drawn(drawn, _plot(project).id) if list(a.rows) == [4])
    assert out.get_color() == "red" and out.get_marker() == "x"
    assert out.get_linestyle() == "None"


def test_a_line_without_markers_still_shows_its_left_out_points() -> None:
    drawn = render(_project(LinePlot, left_out=[4]).figures[0], _data)
    out = next(a for a in drawn.axes[0].lines if list(getattr(a, "rows", [])) == [4])
    assert out.get_marker() not in (None, "None", "")


def test_leaving_a_point_out_fits_again_in_the_same_step() -> None:
    project = _project()
    history = History(project)
    history.push(refit(project, _fit(project).id, _data))
    pulled = _fit(project).result.parameters["a"]
    before = dumps(project)
    history.push(set_left_out(project, _plot(project).id, [4], _data))
    assert _plot(project).left_out == [4]
    assert _fit(project).result.parameters["a"] == pytest.approx(2.0)
    assert pulled != pytest.approx(2.0)
    assert history.undo_text == "Leave out row 5"
    history.undo()
    assert dumps(project) == before
    history.redo()
    history.push(set_left_out(project, _plot(project).id, [], _data))
    assert history.undo_text == "Take row 5 back in"


def test_leaving_out_too_many_points_for_a_fit_is_refused() -> None:
    project = _project()
    with pytest.raises(FitError, match="needs more than 2 valid points"):
        set_left_out(project, _plot(project).id, list(range(8)), _data)


def test_a_left_out_row_the_data_lacks_is_reported() -> None:
    project = _project(left_out=[4, 12])
    messages = [i.message for i in validate_references(project, _data)]
    assert any("row 13 is left out, but the data has 10 rows" in m for m in messages)


def test_the_fit_of_a_plot_skips_its_left_out_points() -> None:
    project = _project(left_out=[4])
    History(project).push(refit(project, _fit(project).id, _data))
    result = _fit(project).result.parameters
    assert np.allclose(evaluate(PredefinedFit(name="linear"), result, T[:4]), U[:4])
