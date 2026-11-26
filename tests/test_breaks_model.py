"""Broken axes in the model: what a break is, which axis may have one, and
which breaks a panel's axis is drawn with."""

from __future__ import annotations

import json

import numpy as np
import pytest
from pydantic import ValidationError

from figscribe.commands import CommandError, History, InsertItem, SetField
from figscribe.model import (
    AllanDeviationPlot,
    ArrayRef,
    Axes,
    AxisSpec,
    ColumnRef,
    Figure,
    GridLayout,
    ImagePlot,
    NumpySource,
    Project,
    dumps,
    loads,
    validate_references,
)
from figscribe.model.breaks import breaks_blocked, effective_breaks


def test_a_new_axis_has_no_break() -> None:
    assert AxisSpec().breaks == []


@pytest.mark.parametrize(
    "breaks",
    [
        [(5, 5)],  # empty
        [(7, 5)],  # backwards
        [(5, 7), (6, 9)],  # overlapping
        [(5, 7), (7, 9)],  # touching: nothing is left between them
        [(8, 9), (1, 2)],  # out of order
        [(1, float("inf"))],
    ],
)
def test_breaks_that_make_no_sense_are_refused(breaks) -> None:
    with pytest.raises(ValidationError):
        AxisSpec(breaks=breaks)


def test_breaks_roundtrip_and_an_older_file_has_none(project: Project) -> None:
    project.figures[0].axes[0].x.breaks = [(2.0, 3.0), (5.0, 6.0)]
    assert loads(dumps(project)).figures[0].axes[0].x.breaks == [(2, 3), (5, 6)]
    document = json.loads(dumps(project))
    del document["figures"][0]["axes"][0]["x"]["breaks"]
    assert loads(json.dumps(document)).figures[0].axes[0].x.breaks == []


def _figure(**x_of_each) -> Figure:
    return Figure(
        layout=GridLayout(rows=2, share_x="col"),
        axes=[
            Axes(row=0, x=x_of_each.get("top", AxisSpec())),
            Axes(row=1, x=x_of_each.get("bottom", AxisSpec())),
        ],
    )


def test_panels_sharing_an_axis_are_broken_alike() -> None:
    figure = _figure(bottom=AxisSpec(breaks=[(2, 3)]))
    assert effective_breaks(figure, 0, "x") == [(2, 3)]
    assert effective_breaks(figure, 1, "x") == [(2, 3)]
    assert effective_breaks(figure, 0, "y") == []


def test_only_a_linear_axis_is_broken_and_never_the_right_one() -> None:
    log = AxisSpec(scale="log", breaks=[(2, 3)])
    figure = Figure(axes=[Axes(x=log, y_right=AxisSpec(breaks=[(1, 2)]))])
    assert effective_breaks(figure, 0, "x") == []
    assert "linear" in breaks_blocked(figure, 0, "x")
    assert effective_breaks(figure, 0, "y_right") == []
    assert "right" in breaks_blocked(figure, 0, "y_right")


def test_a_linear_panel_sharing_with_a_log_one_is_not_broken() -> None:
    figure = _figure(top=AxisSpec(breaks=[(2, 3)]), bottom=AxisSpec(scale="log"))
    assert effective_breaks(figure, 0, "x") == []


def test_an_image_keeps_its_axes_whole() -> None:
    image = ImagePlot(data=ArrayRef(source="s"))
    figure = Figure(axes=[Axes(x=AxisSpec(breaks=[(2, 3)]), artists=[image])])
    assert effective_breaks(figure, 0, "x") == []
    assert "image" in breaks_blocked(figure, 0, "x")


@pytest.mark.parametrize(
    ("path", "value"),
    [(("x", "scale"), "log"), (("x", "scale"), "symlog")],
)
def test_a_command_does_not_make_a_broken_axis_logarithmic(
    project: Project, path, value
) -> None:
    axes = project.figures[0].axes[0]
    history = History(project)
    history.push(SetField(axes.id, ("x", "breaks"), [(2.0, 3.0)]))
    with pytest.raises(CommandError, match="linear"):
        history.push(SetField(axes.id, path, value))
    assert axes.x.scale == "linear"


def test_a_command_does_not_put_an_image_on_a_broken_axis(project: Project) -> None:
    axes = project.figures[0].axes[0]
    history = History(project)
    history.push(SetField(axes.id, ("x", "breaks"), [(2.0, 3.0)]))
    with pytest.raises(CommandError, match="image"):
        history.push(
            InsertItem(axes.id, "artists", ImagePlot(data=ArrayRef(source="s")))
        )


def test_the_problem_list_names_what_a_file_cannot_draw_broken(
    project: Project,
) -> None:
    figure = project.figures[0]
    figure.axes[0].x.scale = "log"
    figure.axes[0].x.breaks = [(2.0, 3.0)]
    messages = [str(issue) for issue in validate_references(project)]
    assert any("only a linear axis can be broken" in m for m in messages)


def test_the_problem_list_says_when_shared_panels_disagree(project: Project) -> None:
    figure = project.figures[0]
    figure.layout.share_x = "col"
    figure.axes[0].x.breaks = [(2.0, 3.0)]
    figure.axes[1].x.breaks = [(4.0, 5.0)]
    messages = [str(issue) for issue in validate_references(project)]
    assert any("different breaks" in m for m in messages)


def test_the_problem_list_counts_the_points_of_an_allan_deviation() -> None:
    plot = AllanDeviationPlot(values=ColumnRef(source="s", column="y"))
    panel = Axes(x=AxisSpec(breaks=[(3.0, 5.0)]), artists=[plot])
    source = NumpySource(id="s", path="y.npy", sha256="0" * 64, columns=["y"])
    project = Project(sources=[source], figures=[Figure(axes=[panel])])
    noise = np.random.default_rng(1).normal(size=100)  # tau = 1, 2, 4, 8, ...
    messages = [str(i) for i in validate_references(project, lambda ref: noise)]
    assert any("1 point lies in a break" in m for m in messages), messages
