"""Axis labels in line across panels, and their distance to the axis (F5.9)."""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

from figscribe.model import (
    ArrayRef,
    Axes,
    AxisSpec,
    Colorbar,
    Figure,
    GridLayout,
    ImagePlot,
    Inset,
    LinePlot,
)
from figscribe.render import render


def _stacked(ref, **fields) -> Figure:
    """Two panels in a column whose tick numbers differ in width."""
    short = AxisSpec(label="short", limits=(0.0, 1.0))
    long = AxisSpec(label="long", limits=(0.0, 5000.0))
    plot = LinePlot(x=ref("t"), y=ref("U"))
    constrained = fields.pop("constrained", True)
    return Figure(
        layout=GridLayout(rows=2, constrained_layout=constrained),
        axes=[
            Axes(y=short, artists=[plot]),
            Axes(row=1, y=long, artists=[LinePlot(x=ref("t"), y=ref("U"))]),
        ],
        **fields,
    )


def _drawn(figure: Figure, data):
    fig = render(figure, data)
    FigureCanvasAgg(fig).draw()
    return fig


def _label_x(ax) -> float:
    return ax.yaxis.label.get_window_extent().x0


def _gap(ax) -> float:
    """Pixels between the y label and the panel's left edge."""
    return ax.get_window_extent().x0 - ax.yaxis.label.get_window_extent().x1


@pytest.mark.parametrize("constrained", [True, False])
def test_y_labels_of_a_column_are_aligned_by_default(
    ref, data, constrained: bool
) -> None:
    figure = _stacked(ref, constrained=constrained)
    assert figure.align_labels is True
    top, bottom = _drawn(figure, data).axes
    assert _label_x(top) == pytest.approx(_label_x(bottom), abs=0.01)


@pytest.mark.parametrize("constrained", [True, False])
def test_without_alignment_each_label_follows_its_numbers(
    ref, data, constrained: bool
) -> None:
    figure = _stacked(ref, constrained=constrained, align_labels=False)
    top, bottom = _drawn(figure, data).axes
    assert _label_x(top) - _label_x(bottom) > 5.0  # pixels: the wide numbers


def test_x_labels_of_a_row_are_aligned(ref, data) -> None:
    def figure(aligned: bool) -> Figure:
        return Figure(
            align_labels=aligned,
            layout=GridLayout(cols=2, constrained_layout=False),
            axes=[
                Axes(
                    x=AxisSpec(label="t", tick_size=20.0),
                    artists=[LinePlot(x=ref("t"), y=ref("U"))],
                ),
                Axes(
                    col=1,
                    x=AxisSpec(label="t"),
                    artists=[LinePlot(x=ref("t"), y=ref("U"))],
                ),
            ],
        )

    def label_y(aligned: bool) -> list[float]:
        axes = _drawn(figure(aligned), data).axes
        return [ax.xaxis.label.get_window_extent().y0 for ax in axes]

    low, high = label_y(True)
    assert low == pytest.approx(high, abs=0.01)
    low, high = label_y(False)
    assert abs(low - high) > 5.0


def test_one_panel_looks_the_same_with_and_without(ref, data) -> None:
    def pixels(aligned: bool) -> bytes:
        figure = Figure(
            align_labels=aligned,
            axes=[
                Axes(y=AxisSpec(label="U"), artists=[LinePlot(x=ref("t"), y=ref("U"))])
            ],
        )
        return bytes(_drawn(figure, data).canvas.buffer_rgba())

    assert pixels(True) == pixels(False)


def test_a_label_distance_moves_the_label(ref, data) -> None:
    def x_of(pad: float | None) -> float:
        figure = Figure(
            align_labels=False,
            axes=[
                Axes(
                    y=AxisSpec(label="U", labelpad=pad),
                    artists=[LinePlot(x=ref("t"), y=ref("U"))],
                )
            ],
        )
        return _gap(_drawn(figure, data).axes[0])

    default = x_of(None)
    assert x_of(20.0) > default + 10.0  # further from the axis, in pixels
    assert x_of(0.0) < default


def test_a_label_distance_also_works_with_alignment(ref, data) -> None:
    figure = _stacked(ref)
    top, bottom = _drawn(figure, data).axes
    together = _gap(top), _gap(bottom)
    figure.axes[0].y.labelpad = 20.0
    top, bottom = _drawn(figure, data).axes
    assert _gap(top) > together[0] + 10.0  # its own distance moves it alone
    assert _gap(bottom) == pytest.approx(together[1], abs=0.5)


def _two_rows_with_right_axes(ref, aligned: bool) -> Figure:
    """Two rows, each with a right y axis, and an inset in the first."""
    first = Axes(
        y=AxisSpec(label="left", limits=(0.0, 1.0)),
        y_right=AxisSpec(label="right", limits=(0.0, 1.0)),
        artists=[LinePlot(x=ref("t"), y=ref("U"))],
    )
    second = Axes(
        row=1,
        y=AxisSpec(label="left", limits=(0.0, 5000.0)),
        y_right=AxisSpec(label="right", limits=(0.0, 5000.0)),
        artists=[LinePlot(x=ref("t"), y=ref("U"))],
    )
    inset = Axes(
        inset=Inset(parent=first.id, bounds=(0.5, 0.5, 0.3, 0.3)),
        artists=[LinePlot(x=ref("t"), y=ref("U"))],
    )
    return Figure(
        align_labels=aligned, layout=GridLayout(rows=2), axes=[first, second, inset]
    )


def test_right_axes_are_aligned_with_each_other_and_insets_are_left_out(
    ref, data
) -> None:
    def positions(aligned: bool) -> tuple[float, float]:
        figure = _two_rows_with_right_axes(ref, aligned)
        fig = _drawn(figure, data)
        by_gid = {ax.get_gid(): ax for ax in fig.axes}
        ends = [
            by_gid[f"{axes.id}#right"].yaxis.label.get_window_extent().x1
            for axes in figure.axes[:2]
        ]
        lefts = [_label_x(by_gid[axes.id]) for axes in figure.axes[:2]]
        return abs(ends[0] - ends[1]), abs(lefts[0] - lefts[1])

    right, left = positions(True)
    assert right < 0.01 and left < 0.01
    right, left = positions(False)
    assert right > 5.0 and left > 5.0


def test_a_colour_bar_does_not_break_the_alignment(ref, data) -> None:
    figure = Figure(
        layout=GridLayout(rows=2),
        axes=[
            Axes(y=AxisSpec(label="a"), artists=[LinePlot(x=ref("t"), y=ref("U"))]),
            Axes(
                row=1,
                y=AxisSpec(label="b"),
                artists=[
                    ImagePlot(data=ArrayRef(source="img"), colorbar=Colorbar(label="c"))
                ],
            ),
        ],
    )

    def resolve(reference):
        if isinstance(reference, ArrayRef):
            return np.arange(12.0).reshape(3, 4)
        return np.linspace(0.0, 1.0, 21)

    fig = _drawn(figure, resolve)
    assert len(fig.axes) == 3  # two panels and the bar


def _with_colour_bar(ref, *, cols: int, constrained: bool) -> Figure:
    """Panel A a line; panel B an image with a colour bar, to its right
    (`cols` = 2) or below it. Without the constrained layout, Matplotlib
    splits the parent's grid cell for the bar."""
    first = Axes(
        x=AxisSpec(label="a"),
        y=AxisSpec(label="a"),
        artists=[LinePlot(x=ref("t"), y=ref("U"))],
    )
    second = Axes(
        row=0 if cols == 2 else 1,
        col=1 if cols == 2 else 0,
        x=AxisSpec(label="b"),
        y=AxisSpec(label="b"),
        artists=[ImagePlot(data=ArrayRef(source="img"), colorbar=Colorbar(label="c"))],
    )
    layout = (
        GridLayout(cols=2, constrained_layout=constrained)
        if cols == 2
        else GridLayout(rows=2, constrained_layout=constrained)
    )
    return Figure(layout=layout, axes=[first, second])


def _resolve(reference):
    if isinstance(reference, ArrayRef):
        return np.arange(12.0).reshape(3, 4)
    return np.linspace(0.0, 1.0, 21)


def _label_positions(figure: Figure) -> list[float]:
    """Where each panel's x and y label start, in drawing order."""
    fig = _drawn(figure, _resolve)
    return [
        value
        for ax in fig.axes[:2]
        for value in (
            ax.xaxis.label.get_window_extent().y0,
            ax.yaxis.label.get_window_extent().x0,
        )
    ]


@pytest.mark.parametrize("cols", [1, 2])
@pytest.mark.parametrize("constrained", [True, False])
def test_a_colour_bar_panel_keeps_its_labels_where_they_are(
    ref, cols: int, constrained: bool
) -> None:
    """Without the constrained layout Matplotlib splits the parent's grid cell
    for the bar, and the alignment would count its rows and columns from
    zero again, pulling the label out of the figure."""
    figure = _with_colour_bar(ref, cols=cols, constrained=constrained)
    figure.align_labels = False
    off = _label_positions(figure)
    figure.align_labels = True
    on = _label_positions(figure)
    assert on == pytest.approx(off, abs=0.01)


def test_the_other_panels_of_a_column_are_still_lined_up_beside_a_colour_bar(
    ref,
) -> None:
    figure = _with_colour_bar(ref, cols=2, constrained=False)
    figure.axes[0].y.label = "U"
    figure.axes.append(
        Axes(
            row=1,
            y=AxisSpec(label="U", limits=(0.0, 5000.0)),
            artists=[LinePlot(x=ref("t"), y=ref("U"))],
        )
    )
    figure.layout = GridLayout(rows=2, cols=2, constrained_layout=False)
    fig = _drawn(figure, _resolve)
    by_gid = {ax.get_gid(): ax for ax in fig.axes}
    top, bar_panel, bottom = (by_gid[axes.id] for axes in figure.axes)
    assert _label_x(top) == pytest.approx(_label_x(bottom), abs=0.01)
    figure.align_labels = False
    plain = _drawn(figure, _resolve)
    by_gid = {ax.get_gid(): ax for ax in plain.axes}
    assert _label_x(bar_panel) == pytest.approx(
        _label_x(by_gid[figure.axes[1].id]), abs=0.01
    )
