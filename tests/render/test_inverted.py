"""An axis drawn backwards (F5.2), also while its range is automatic."""

from __future__ import annotations

import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

from figscribe.model import Axes, AxisSpec, Figure, GridLayout, LinePlot
from figscribe.render import render
from figscribe.render.ticks import reversed_axis


def _drawn(figure: Figure, data):
    fig = render(figure, data)
    FigureCanvasAgg(fig).draw()
    return fig


def _panel(ref, **specs) -> Axes:
    return Axes(artists=[LinePlot(x=ref("t"), y=ref("U"))], **specs)


def _runs_backwards(low_high: tuple[float, float]) -> bool:
    return low_high[0] > low_high[1]


@pytest.mark.parametrize("limits", [None, (0.0, 10.0), (10.0, 0.0)])
def test_the_flag_reverses_an_automatic_or_a_given_range(ref, data, limits) -> None:
    spec = AxisSpec(limits=limits, inverted=True)
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=spec, y=spec)]), data).axes
    assert _runs_backwards(ax.get_xlim()) and _runs_backwards(ax.get_ylim())


def test_without_the_flag_the_axis_runs_forwards(ref, data) -> None:
    (ax,) = _drawn(Figure(axes=[_panel(ref)]), data).axes
    assert not _runs_backwards(ax.get_xlim())


def test_the_ticks_follow_a_reversed_automatic_axis(ref, data) -> None:
    spec = AxisSpec(inverted=True, major_step=2.0)
    (ax,) = _drawn(Figure(axes=[_panel(ref, x=spec)]), data).axes
    shown = [
        t for t in ax.get_xticks() if min(ax.get_xlim()) <= t <= max(ax.get_xlim())
    ]
    assert _runs_backwards(ax.get_xlim()) and len(shown) >= 3


def test_the_right_axis_is_reversed_on_its_own(ref, data) -> None:
    panel = _panel(ref, y_right=AxisSpec(inverted=True))
    left, right = _drawn(Figure(axes=[panel]), data).axes
    assert not _runs_backwards(left.get_ylim()) and _runs_backwards(right.get_ylim())


def test_panels_sharing_an_axis_are_reversed_together(ref, data) -> None:
    figure = Figure(
        layout=GridLayout(rows=2, share_x="col"),
        axes=[_panel(ref, x=AxisSpec(inverted=True)), _panel(ref, x=AxisSpec())],
    )
    top, bottom = _drawn(figure, data).axes
    assert _runs_backwards(top.get_xlim()) and _runs_backwards(bottom.get_xlim())


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (AxisSpec(), False),
        (AxisSpec(inverted=True), True),
        (AxisSpec(limits=(0.0, 1.0)), False),
        (AxisSpec(limits=(1.0, 0.0)), True),
        (AxisSpec(limits=(0.0, 1.0), inverted=True), True),
    ],
)
def test_an_axis_is_reversed_by_the_flag_or_by_its_range(spec, expected) -> None:
    assert reversed_axis(spec) is expected
