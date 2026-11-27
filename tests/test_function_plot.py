"""A function drawn without data (roadmap F15, decision 0078)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.colors
import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

from figscribe.commands import CommandError, History, InsertItem
from figscribe.function import new_function, set_expression
from figscribe.io import csv_source, load_data
from figscribe.model import (
    Axes,
    AxisSpec,
    ColumnRef,
    Conversion,
    Figure,
    FunctionPlot,
    GridLayout,
    LinePlot,
    Project,
    dumps,
    loads,
    validate_references,
)
from figscribe.render import render
from figscribe.units import set_conversion


def _project(tmp_path: Path, *functions: FunctionPlot, **x) -> Project:
    t = np.linspace(1.0, 10.0, 10)
    rows = "\n".join(f"{a:g},{2 * a:g}" for a in t)
    (tmp_path / "d.csv").write_text("t,U\n" + rows + "\n", encoding="utf-8")
    source = csv_source(tmp_path / "d.csv", tmp_path)
    plot = LinePlot(
        x=ColumnRef(source=source.id, column="t"),
        y=ColumnRef(source=source.id, column="U"),
    )
    panel = Axes(x=AxisSpec(**x), artists=[plot, *functions])
    return Project(sources=[source], figures=[Figure(axes=[panel])])


def _drawn(project: Project, folder: Path):
    figure = render(project.figures[0], load_data(project, folder))
    FigureCanvasAgg(figure).draw()
    return figure


def _line(figure, gid: str):
    (line,) = [ln for ax in figure.axes for ln in ax.lines if ln.get_gid() == gid]
    return line


def _problems(project: Project, folder: Path) -> list[str]:
    data = load_data(project, folder)
    return [str(i) for i in validate_references(project, data)]


def test_each_name_in_the_formula_has_a_value() -> None:
    made = new_function("a * exp(-x / tau)")
    assert made.parameters == {"a": 1.0, "tau": 1.0}
    assert list(made.parameters) == ["a", "tau"]  # as they first appear
    assert new_function("1e-11 / sqrt(x)").parameters == {}


@pytest.mark.parametrize("bad", ["a +", "open('x')", "np * x", ""])
def test_a_formula_that_cannot_be_read_is_refused(bad) -> None:
    with pytest.raises(CommandError):
        new_function(bad)


def test_a_changed_formula_keeps_the_values_that_remain(tmp_path: Path) -> None:
    made = new_function("a * exp(-x / tau)")
    made.parameters = {"a": 3.0, "tau": 5.0}
    project = _project(tmp_path, made)
    before = dumps(project)
    history = History(project)
    history.push(set_expression(project, made.id, "a * x + c"))
    function = project.figures[0].axes[0].artists[1]
    assert function.parameters == {"a": 3.0, "c": 1.0}
    history.undo()
    assert dumps(project) == before  # one step
    with pytest.raises(CommandError):
        history.push(set_expression(project, made.id, "a *"))


def test_it_is_kept_in_the_file() -> None:
    made = new_function("a * x")
    made.curve_range, made.label = (0.0, 4.0), "guide"
    project = Project(figures=[Figure(axes=[Axes(artists=[made])])])
    again = loads(dumps(project)).figures[0].axes[0].artists[0]
    assert (again.expression, again.curve_range) == ("a * x", (0.0, 4.0))
    with pytest.raises(ValueError, match="curve"):
        FunctionPlot(expression="x", curve_range=(2.0, 1.0))


def test_a_file_with_a_bad_formula_opens_and_says_so(tmp_path: Path) -> None:
    project = _project(tmp_path, FunctionPlot(expression="a *"))
    project = loads(dumps(project))
    (problem,) = _problems(project, tmp_path)
    assert "formula" in problem
    drawn = _drawn(project, tmp_path)
    assert len(drawn.axes[0].lines) == 1  # the data only


@pytest.mark.parametrize(
    ("x", "curve", "ends"),
    [
        ({}, None, (1.0, 10.0)),  # the data
        ({"limits": (0.0, 20.0)}, None, (0.0, 20.0)),
        ({"limits": (20.0, 0.0)}, None, (0.0, 20.0)),
        ({"limits": (0.0, 20.0)}, (2.0, 5.0), (2.0, 5.0)),
    ],
)
def test_where_it_is_drawn(tmp_path: Path, x, curve, ends) -> None:
    made = new_function("x")
    made.curve_range = curve
    project = _project(tmp_path, made, **x)
    line = _line(_drawn(project, tmp_path), made.id)
    assert (line.get_xdata()[0], line.get_xdata()[-1]) == ends


@pytest.mark.parametrize("first", [True, False], ids=["first", "last"])
def test_it_moves_no_limits_of_a_panel_with_data(tmp_path: Path, first) -> None:
    """Far above the data and beyond them, drawn before or after the plots."""
    made = new_function("1000 * x")
    made.curve_range = (-50.0, 50.0)
    project = _project(tmp_path)
    axes = project.figures[0].axes[0]
    plain = _drawn(project, tmp_path).axes[0]
    expected = plain.get_xlim(), plain.get_ylim()
    axes.artists.insert(0 if first else 1, made)
    ax = _drawn(project, tmp_path).axes[0]
    assert (ax.get_xlim(), ax.get_ylim()) == expected


def test_it_moves_none_on_a_shared_axis_either(tmp_path: Path) -> None:
    made = new_function("1000 * x")
    project = _project(tmp_path, made)
    figure = project.figures[0]
    figure.layout = GridLayout(cols=2, share_y="row")
    figure.axes.append(Axes(col=1, artists=[figure.axes[0].artists[0].model_copy()]))
    figure.axes[1].artists[0].id = "other"
    assert max(_drawn(project, tmp_path).axes[0].get_ylim()) < 30


def test_a_panel_of_functions_alone_is_scaled_by_them() -> None:
    made = new_function("1000 * x")
    made.curve_range = (0.0, 5.0)
    figure = render(Figure(axes=[Axes(artists=[made])]), lambda ref: None)
    FigureCanvasAgg(figure).draw()
    assert max(figure.axes[0].get_ylim()) > 4000


def test_it_takes_no_color_from_the_cycle(tmp_path: Path) -> None:
    made = new_function("x")
    project = _project(tmp_path, made)
    axes = project.figures[0].axes[0]
    axes.artists.append(axes.artists[0].model_copy(update={"id": "later"}))
    lines = _drawn(project, tmp_path).axes[0].lines
    colors = [matplotlib.colors.to_hex(ln.get_color()) for ln in lines]
    assert colors == ["#1f77b4", "#000000", "#ff7f0e"]


def test_without_data_and_range_it_says_what_is_missing() -> None:
    made = new_function("x")
    project = Project(figures=[Figure(axes=[Axes(artists=[made])])])
    (problem,) = [str(i) for i in validate_references(project, lambda ref: None)]
    assert "range" in problem


def test_a_unit_change_moves_its_range_and_not_the_formula(tmp_path: Path) -> None:
    made = new_function("2 * x")
    made.curve_range = (1.0, 5.0)
    project = _project(tmp_path, made)
    plot = project.figures[0].axes[0].artists[0]
    data = load_data(project, tmp_path)
    ms = Conversion(factor=1000.0, unit="ms")
    History(project).push(set_conversion(project, plot.id, "x", ms, data))
    function = project.figures[0].axes[0].artists[1]
    assert function.curve_range == (1000.0, 5000.0)
    assert function.expression == "2 * x"


def test_insert_and_undo(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = dumps(project)
    history = History(project)
    history.push(
        InsertItem(project.figures[0].axes[0].id, "artists", new_function("x"))
    )
    history.undo()
    assert dumps(project) == before
