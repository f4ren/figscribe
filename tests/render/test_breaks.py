"""A broken axis as drawn: ticks on every stretch and none in a gap, nothing
shown in the gap, no line across it."""

from __future__ import annotations

import io

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PIL import Image

from figscribe.model import (
    Axes,
    AxisSpec,
    Figure,
    GridLayout,
    LinePlot,
    ScatterPlot,
)
from figscribe.render import export_bytes, render
from figscribe.render.breaks import crossings, gap_width, pieces

# x runs from 0 to 20, and one point sits far away at 420, as a measurement at
# the zinc point does.
X = np.r_[np.linspace(0.0, 20.0, 11), 420.0]
Y = np.r_[np.linspace(1.0, 3.0, 11), 9.0]
COLUMNS = {"t": X, "U": Y}


def data(ref):
    return COLUMNS[ref.column]


def _drawn(figure: Figure, view=None):
    fig = render(figure, data, view=view)
    FigureCanvasAgg(fig).draw()
    return fig


def _panel(ref, kind=LinePlot, plot=None, **axes) -> Axes:
    return Axes(artists=[kind(x=ref("t"), y=ref("U"), **(plot or {}))], **axes)


def _ticks(ax, name="x") -> list[float]:
    axis = ax.xaxis if name == "x" else ax.yaxis
    low, high = sorted(axis.get_view_interval())
    return [float(t) for t in axis.get_majorticklocs() if low <= t <= high]


def _marks(ax) -> list:
    return [
        line for line in ax.lines if line.get_gid() is None and not line.get_clip_on()
    ]


X_BREAK = AxisSpec(breaks=[(24.0, 416.0)])


def test_each_stretch_has_numbers_and_the_gap_none(ref) -> None:
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=X_BREAK)])).axes
    ticks = _ticks(ax)
    assert any(t <= 24 for t in ticks) and any(t >= 416 for t in ticks)
    assert not [t for t in ticks if 24 < t < 416]


def test_the_gap_takes_little_room_and_the_stretches_are_to_scale(ref) -> None:
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=X_BREAK)])).axes
    at = ax.transData + ax.transAxes.inverted()
    left, right = (at.transform((x, 0))[0] for x in (24.0, 416.0))
    assert 0.01 < right - left < 0.04
    per_unit = [
        (at.transform((b, 0))[0] - at.transform((a, 0))[0]) / (b - a)
        for a, b in ((0, 10), (10, 20), (417, 419))
    ]
    assert per_unit == pytest.approx([per_unit[0]] * 3)


def test_without_a_break_nothing_changes(ref) -> None:
    (ax,) = _drawn(Figure(axes=[_panel(ref)])).axes
    assert ax.get_xscale() == "linear" and _marks(ax) == []


@pytest.mark.parametrize(("open_frame", "count"), [(False, 4), (True, 2)])
def test_break_marks_stand_on_the_lines_that_are_drawn(ref, open_frame, count) -> None:
    figure = Figure(open_frame=open_frame, axes=[_panel(ref, x=X_BREAK)])
    (ax,) = _drawn(figure).axes
    assert sum(len(line.get_xdata()) for line in _marks(ax)) == count


def test_no_line_is_drawn_across_a_break(ref) -> None:
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=X_BREAK)])).axes
    (line,) = [line for line in ax.lines if line.get_gid()]
    xs = line.get_xdata()
    at = int(np.flatnonzero(np.isnan(xs))[0])
    assert (xs[at - 1], xs[at + 1]) == (20.0, 420.0)
    # A click still names the right row of the data.
    assert list(line.rows) == [*range(11), -1, 11]


def test_points_without_a_line_keep_their_data(ref) -> None:
    figure = Figure(axes=[_panel(ref, ScatterPlot, x=X_BREAK)])
    (ax,) = _drawn(figure).axes
    assert len(ax.collections[0].get_offsets()) == len(X)


def _pixels(figure: Figure, transparent=False) -> np.ndarray:
    png = export_bytes(figure, data, ".png", transparent)
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))


def _gap_column(figure: Figure) -> tuple[int, int, int]:
    """The pixel column in the middle of the x break, and the rows of the
    panel's top and bottom edge."""
    fig = _drawn(figure)
    ax = fig.axes[0]
    ends = [ax.transData.transform((x, 0))[0] for x in (24.0, 416.0)]
    box = ax.bbox
    height = fig.bbox.height
    return int(sum(ends) / 2), int(height - box.y1), int(height - box.y0)


def test_nothing_is_painted_in_the_gap(ref) -> None:
    """Not the plot, the horizontal grid lines or the frame; a transparent
    export shows the background through."""
    spec = AxisSpec(breaks=[(24.0, 416.0)])
    panel = _panel(ref, plot={"linewidth": 3.0}, x=spec, grid=True)
    figure = Figure(dpi=150, ticks_all_sides=False, axes=[panel])
    column, top, bottom = _gap_column(figure)
    pixels = _pixels(figure, transparent=True)
    assert pixels[top - 2 : bottom + 2, column, 3].max() == 0


def test_the_gap_stays_cut_when_drawn_again_at_another_size(ref) -> None:
    """As the preview does after setting its resolution."""
    panel = _panel(ref, x=X_BREAK, grid=True)
    fig = _drawn(Figure(axes=[panel], ticks_all_sides=False))
    fig.set_dpi(220)
    canvas = FigureCanvasAgg(fig)
    canvas.draw()
    ax = fig.axes[0]
    column = int(sum(ax.transData.transform((x, 0))[0] for x in (24, 416)) / 2)
    rows = np.asarray(canvas.buffer_rgba())
    height = rows.shape[0]
    inside = rows[int(height - ax.bbox.y1) : int(height - ax.bbox.y0), column, :3]
    assert (inside == 255).all()


def test_a_y_break_and_both_directions(ref) -> None:
    panel = _panel(ref, x=X_BREAK, y=AxisSpec(breaks=[(4.0, 8.0)]))
    (ax,) = _drawn(Figure(axes=[panel])).axes
    assert not [t for t in _ticks(ax, "y") if 4 < t < 8]
    assert any(t <= 4 for t in _ticks(ax, "y")) and any(t >= 8 for t in _ticks(ax, "y"))
    assert sum(len(line.get_xdata()) for line in _marks(ax)) == 8


def test_several_breaks(ref) -> None:
    spec = AxisSpec(breaks=[(6.0, 12.0), (24.0, 416.0)])
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=spec)])).axes
    ticks = _ticks(ax)
    assert not [t for t in ticks if 6 < t < 12 or 24 < t < 416]
    assert len([line for line in ax.lines if line.get_gid()]) == 1


def test_an_automatic_number_keeps_clear_of_the_break_marks(ref) -> None:
    panel = _panel(ref, ScatterPlot, y=AxisSpec(breaks=[(3.8, 8.0)]))
    (ax,) = _drawn(Figure(axes=[panel])).axes
    ticks = _ticks(ax, "y")
    assert 9.0 in ticks and 8.0 not in ticks


def test_typed_ticks_in_a_gap_are_left_out_with_their_labels(ref) -> None:
    spec = AxisSpec(
        breaks=[(24.0, 416.0)], ticks=[0, 100, 420], tick_labels=["a", "b", "c"]
    )
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=spec)])).axes
    assert _ticks(ax) == [0, 420]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["a", "c"]


def test_a_tick_step_applies_on_each_stretch(ref) -> None:
    spec = AxisSpec(breaks=[(24.0, 416.0)], major_step=5.0)
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=spec)])).axes
    assert _ticks(ax) == [0, 5, 10, 15, 20, 420]


@pytest.mark.parametrize("limits", [(-2.0, 430.0), (430.0, -2.0)])
def test_a_given_range_also_turned_around(ref, limits) -> None:
    spec = AxisSpec(breaks=[(24.0, 416.0)], limits=limits)
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=spec)])).axes
    assert ax.get_xlim() == pytest.approx(limits)
    assert any(t >= 416 for t in _ticks(ax))


def test_a_break_outside_the_data_does_nothing(ref) -> None:
    spec = AxisSpec(breaks=[(500.0, 600.0)])
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=spec)])).axes
    assert ax.get_xscale() == "linear" and _marks(ax) == []


def test_a_zoomed_view_keeps_the_width_of_the_gap(ref) -> None:
    panel = _panel(ref, x=X_BREAK)
    figure = Figure(axes=[panel])

    def squeezed(view=None) -> float:
        (ax,) = _drawn(figure, view).axes
        forward = ax.xaxis.get_transform().transform
        return float(np.diff(forward(np.array([[24.0, 0], [416.0, 0]]))[:, 0])[0])

    view = {panel.id: ((10.0, 418.0), (0.0, 10.0))}
    assert squeezed(view) == pytest.approx(squeezed())


def test_a_shared_axis_is_broken_in_both_panels(ref) -> None:
    figure = Figure(
        layout=GridLayout(rows=2, share_x="col"),
        axes=[_panel(ref, row=0), _panel(ref, row=1, x=X_BREAK)],
    )
    top, bottom = _drawn(figure).axes
    for ax in (top, bottom):
        assert ax.get_xscale() == "function" and _marks(ax)
    assert top.get_xlim() == bottom.get_xlim()


def test_the_right_axis_is_cut_along_with_x(ref) -> None:
    panel = _panel(ref, x=X_BREAK, y_right=AxisSpec())
    panel.artists.append(LinePlot(x=ref("t"), y=ref("U"), axis="right"))
    left, right = _drawn(Figure(axes=[panel])).axes
    (line,) = [line for line in right.lines if line.get_gid()]
    assert line.get_clip_path() is not None and np.isnan(line.get_xdata()).any()


def test_the_pieces_between_breaks() -> None:
    assert pieces([(2, 3), (5, 6)], 0, 10) == [(0, 2), (3, 5), (6, 10)]
    assert pieces([(2, 3)], 2.5, 10) == [(3, 10)]
    assert pieces([], 0, 1) == [(0, 1)]


def test_the_width_of_a_gap_is_a_share_of_the_axis() -> None:
    width = gap_width([(10, 90)], 0, 100)
    assert width / (20 + width) == pytest.approx(0.025, rel=1e-3)


def test_which_steps_cross_a_break() -> None:
    x = np.array([0.0, 1.0, 5.0, np.nan, 9.0])
    assert list(crossings(x, x, [(2, 4)], [])) == [2]
    assert list(crossings(x, x, [], [(0.2, 0.8)])) == [1]
