"""An open frame (F5.4): only the left and bottom axis, no tick marks on the
other two sides."""

from __future__ import annotations

import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

from figscribe.model import Axes, AxisSpec, Figure, LinePlot
from figscribe.render import render


def _drawn(figure: Figure, data):
    fig = render(figure, data)
    FigureCanvasAgg(fig).draw()
    return fig


def _panel(ref, **fields) -> Axes:
    return Axes(artists=[LinePlot(x=ref("t"), y=ref("U"))], **fields)


def _shown(ax) -> dict[str, bool]:
    return {name: spine.get_visible() for name, spine in ax.spines.items()}


def _tick_marks(ax) -> dict[str, bool]:
    """Whether tick marks are drawn on each side, major and minor."""
    x, y = ax.xaxis, ax.yaxis
    ticks = {
        "bottom": x.get_major_ticks()[0].tick1line.get_visible(),
        "top": x.get_major_ticks()[0].tick2line.get_visible(),
        "left": y.get_major_ticks()[0].tick1line.get_visible(),
        "right": y.get_major_ticks()[0].tick2line.get_visible(),
        "minor top": x.get_minor_ticks()[0].tick2line.get_visible()
        if x.get_minor_ticks()
        else False,
        "minor right": y.get_minor_ticks()[0].tick2line.get_visible()
        if y.get_minor_ticks()
        else False,
    }
    return ticks


def test_an_open_frame_leaves_two_axes_and_their_ticks(ref, data) -> None:
    (ax,) = _drawn(Figure(open_frame=True, axes=[_panel(ref)]), data).axes
    assert _shown(ax) == {"left": True, "bottom": True, "top": False, "right": False}
    marks = _tick_marks(ax)
    assert marks["bottom"] and marks["left"]
    assert not any(marks[side] for side in ("top", "right", "minor top", "minor right"))


def test_a_box_stays_as_it_was(ref, data) -> None:
    (ax,) = _drawn(Figure(axes=[_panel(ref)]), data).axes
    assert all(_shown(ax).values())
    marks = _tick_marks(ax)
    assert marks["top"] and marks["right"]  # ticks on all sides, by default


@pytest.mark.parametrize("all_sides", [True, False])
def test_ticks_on_all_sides_do_nothing_in_an_open_frame(ref, data, all_sides) -> None:
    (ax,) = _drawn(
        Figure(open_frame=True, ticks_all_sides=all_sides, axes=[_panel(ref)]), data
    ).axes
    assert not _tick_marks(ax)["top"] and not _tick_marks(ax)["right"]


def test_a_right_axis_keeps_its_line_and_its_ticks(ref, data) -> None:
    panel = _panel(ref, y_right=AxisSpec(label="T"))
    left, right = _drawn(Figure(open_frame=True, axes=[panel]), data).axes
    assert not left.spines["right"].get_visible()
    assert right.spines["right"].get_visible()
    assert right.yaxis.get_major_ticks()[0].tick2line.get_visible()


def test_an_open_frame_beats_a_style_sheet_with_ticks_on_top(ref, data) -> None:
    figure = Figure(open_frame=True, stylesheet="classic", axes=[_panel(ref)])
    (ax,) = _drawn(figure, data).axes
    assert not _tick_marks(ax)["top"] and not _tick_marks(ax)["right"]
