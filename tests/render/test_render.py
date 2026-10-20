"""Renderer: model -> Matplotlib figure, checked structurally.

Pixel-level checks live in test_images.py; these tests assert that each model
field reaches the right Matplotlib property.
"""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.collections import PathCollection

from figscribe.model import (
    Annotation,
    Axes,
    AxisSpec,
    ErrorbarPlot,
    Figure,
    GridLayout,
    Legend,
    LinePlot,
    ScatterPlot,
)
from figscribe.render import render


def test_size_is_converted_from_mm(data) -> None:
    fig = render(Figure(width_mm=127.0, height_mm=50.8, dpi=150.0), data)
    assert tuple(fig.get_size_inches()) == pytest.approx((5.0, 2.0))
    assert fig.dpi == 150.0


def test_unit_format_is_applied_to_labels(data) -> None:
    axes = Axes(x=AxisSpec(label="$t$", unit="s"), y=AxisSpec(label="$U$", unit="V"))
    fig = render(Figure(unit_format="parentheses", axes=[axes]), data)
    ax = fig.axes[0]
    assert ax.get_xlabel() == "$t$ (s)"
    assert ax.get_ylabel() == "$U$ (V)"


def test_axis_settings(data) -> None:
    axes = Axes(
        title="scan",
        x=AxisSpec(scale="log", limits=(0.1, 10.0)),
        y=AxisSpec(scale="symlog", symlog_linthresh=0.5, minor_ticks=False),
        grid=True,
    )
    ax = render(Figure(axes=[axes]), data).axes[0]
    assert ax.get_title() == "scan"
    assert ax.get_xscale() == "log"
    assert ax.get_xlim() == pytest.approx((0.1, 10.0))
    assert ax.get_yscale() == "symlog"
    assert ax.yaxis.get_transform().linthresh == 0.5
    assert all(line.get_visible() for line in ax.xaxis.get_gridlines())


def test_fixed_ticks_and_labels(data) -> None:
    axes = Axes(x=AxisSpec(ticks=[0.0, 5.0, 10.0], tick_labels=["a", "b", "c"]))
    ax = render(Figure(axes=[axes]), data).axes[0]
    assert list(ax.get_xticks()) == [0.0, 5.0, 10.0]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["a", "b", "c"]


def test_line_plot(data, columns, ref) -> None:
    line = LinePlot(
        x=ref("t"),
        y=ref("U"),
        label="signal",
        color="C3",
        linestyle="--",
        linewidth=2.0,
        marker="s",
        markersize=3.0,
        alpha=0.5,
        zorder=4.0,
    )
    ax = render(Figure(axes=[Axes(artists=[line])]), data).axes[0]
    (drawn,) = ax.get_lines()
    assert np.array_equal(drawn.get_xdata(), columns["t"])
    assert np.array_equal(drawn.get_ydata(), columns["U"])
    assert drawn.get_label() == "signal"
    assert drawn.get_linestyle() == "--"
    assert drawn.get_linewidth() == 2.0
    assert drawn.get_marker() == "s"
    assert drawn.get_markersize() == 3.0
    assert drawn.get_alpha() == 0.5
    assert drawn.get_zorder() == 4.0
    assert drawn.get_gid() == line.id


def test_scatter_plot(data, columns, ref) -> None:
    scatter = ScatterPlot(x=ref("t"), y=ref("U"), size=9.0, marker="^")
    ax = render(Figure(axes=[Axes(artists=[scatter])]), data).axes[0]
    (drawn,) = [c for c in ax.collections if isinstance(c, PathCollection)]
    assert np.array_equal(
        drawn.get_offsets(), np.column_stack([columns["t"], columns["U"]])
    )
    assert list(drawn.get_sizes()) == [9.0]
    assert drawn.get_gid() == scatter.id


def test_errorbar_plot(data, columns, ref) -> None:
    bars = ErrorbarPlot(x=ref("t"), y=ref("U"), yerr=ref("dU"), capsize=3.0)
    ax = render(Figure(axes=[Axes(artists=[bars])]), data).axes[0]
    (container,) = ax.containers
    data_line, caplines, _ = container.lines
    assert np.array_equal(data_line.get_ydata(), columns["U"])
    assert len(caplines) == 2  # one lower and one upper cap line
    assert {part.get_gid() for part in container.get_children()} == {bars.id}


def test_unlabelled_artists_stay_out_of_the_legend(data, ref) -> None:
    axes = Axes(
        legend=Legend(visible=True),
        artists=[
            LinePlot(x=ref("t"), y=ref("U"), label="kept"),
            LinePlot(x=ref("t"), y=ref("dU")),
        ],
    )
    legend = render(Figure(axes=[axes]), data).axes[0].get_legend()
    assert [t.get_text() for t in legend.get_texts()] == ["kept"]


def test_dragged_legend_position_overrides_location(data, ref) -> None:
    axes = Axes(
        legend=Legend(
            visible=True, location="upper left", position=(0.7, 0.2), frame=False
        ),
        artists=[LinePlot(x=ref("t"), y=ref("U"), label="a")],
    )
    legend = render(Figure(axes=[axes]), data).axes[0].get_legend()
    assert legend.get_bbox_to_anchor()._bbox.bounds[:2] == pytest.approx((0.7, 0.2))
    assert not legend.get_frame_on()


def test_invisible_legend_is_not_drawn(data, ref) -> None:
    axes = Axes(artists=[LinePlot(x=ref("t"), y=ref("U"), label="a")])
    assert render(Figure(axes=[axes]), data).axes[0].get_legend() is None


def test_grid_placement_and_sharing(data) -> None:
    figure = Figure(
        layout=GridLayout(rows=2, cols=2, share_x="col", height_ratios=[3.0, 1.0]),
        axes=[
            Axes(row=0, col=0, colspan=2),
            Axes(row=1, col=0),
            Axes(row=1, col=1),
        ],
    )
    top, left, right = render(figure, data).axes
    assert top.get_subplotspec().colspan == range(0, 2)
    assert left.get_subplotspec().rowspan == range(1, 2)
    assert right.get_subplotspec().colspan == range(1, 2)
    # "col" joins axes that start in the same column.
    shared = top.get_shared_x_axes()
    assert shared.joined(top, left)
    assert not shared.joined(top, right)


def test_shared_tick_labels_only_on_the_outer_edge(data) -> None:
    figure = Figure(
        layout=GridLayout(rows=2, cols=2, share_x="all", share_y="row"),
        axes=[Axes(row=r, col=c) for r in range(2) for c in range(2)],
    )
    axs = render(figure, data).axes

    assert [ax.xaxis.get_tick_params()["labelbottom"] for ax in axs] == [
        False,
        False,
        True,
        True,
    ]
    assert [ax.yaxis.get_tick_params()["labelleft"] for ax in axs] == [
        True,
        False,
        True,
        False,
    ]


def test_tick_labels_stay_without_a_partner_below_or_left(data) -> None:
    # The bottom-right cell is empty: the top-right axes has nothing below it
    # in its column, and the bottom-left axes nothing to its left in its row.
    figure = Figure(
        layout=GridLayout(rows=2, cols=2, share_x="col", share_y="all"),
        axes=[Axes(row=0, col=0), Axes(row=0, col=1), Axes(row=1, col=0)],
    )
    top_left, top_right, bottom_left = render(figure, data).axes

    assert not top_left.xaxis.get_tick_params()["labelbottom"]
    assert top_right.xaxis.get_tick_params()["labelbottom"]
    assert not top_right.yaxis.get_tick_params()["labelleft"]
    assert bottom_left.yaxis.get_tick_params()["labelleft"]


def test_tick_labels_stay_above_a_partner_of_another_width(data) -> None:
    # Shared limits over a different width: the ticks below do not line up.
    figure = Figure(
        layout=GridLayout(rows=2, cols=2, share_x="all"),
        axes=[
            Axes(row=0, col=0),
            Axes(row=0, col=1),
            Axes(row=1, col=0, colspan=2),
        ],
    )
    axs = render(figure, data).axes
    assert [ax.xaxis.get_tick_params()["labelbottom"] for ax in axs] == [
        True,
        True,
        True,
    ]


def test_tick_labels_stay_beside_a_partner_of_another_height(data) -> None:
    figure = Figure(
        layout=GridLayout(rows=2, cols=2, share_y="all"),
        axes=[Axes(row=0, col=0, rowspan=2), Axes(row=0, col=1)],
    )
    axs = render(figure, data).axes
    assert [ax.yaxis.get_tick_params()["labelleft"] for ax in axs] == [True, True]


def test_tick_labels_hide_above_a_partner_of_the_same_span(data) -> None:
    figure = Figure(
        layout=GridLayout(rows=2, cols=2, share_x="col"),
        axes=[Axes(row=0, col=0, colspan=2), Axes(row=1, col=0, colspan=2)],
    )
    top, bottom = render(figure, data).axes
    assert not top.xaxis.get_tick_params()["labelbottom"]
    assert bottom.xaxis.get_tick_params()["labelbottom"]


def test_unshared_axes_keep_their_tick_labels(data) -> None:
    figure = Figure(layout=GridLayout(rows=2), axes=[Axes(row=0), Axes(row=1)])
    top = render(figure, data).axes[0]
    assert top.xaxis.get_tick_params()["labelbottom"]


def test_share_all_joins_every_axes(data) -> None:
    figure = Figure(
        layout=GridLayout(rows=1, cols=2, share_y="all"),
        axes=[Axes(col=0), Axes(col=1)],
    )
    a, b = render(figure, data).axes
    assert a.get_shared_y_axes().joined(a, b)


def test_artists_not_drawn_yet_are_refused(data) -> None:
    from figscribe.model import ArrayRef, ImagePlot

    axes = Axes(artists=[ImagePlot(data=ArrayRef(source="s"))])
    with pytest.raises(NotImplementedError, match="image"):
        render(Figure(axes=[axes]), data)


def test_a_histogram_leaves_out_values_it_cannot_place(data, ref, columns) -> None:
    from figscribe.model import Histogram

    columns["U"][3] = np.nan
    hist = Histogram(values=ref("U"), bins=[0.0, 0.5, 1.0], density=True, label="h")
    ax = render(Figure(axes=[Axes(artists=[hist])]), data).axes[0]
    heights = [patch.get_height() for patch in ax.patches]
    assert len(heights) == 2 and all(p.get_gid() == hist.id for p in ax.patches)
    assert sum(h * 0.5 for h in heights) == pytest.approx(1.0)  # a density


def test_an_annotation_with_and_without_arrow(data) -> None:
    plain = Annotation(text="peak", position=(0.1, 0.9), coords="axes")
    arrow = Annotation(text="here", position=(2.0, 0.5), arrow_to=(5.0, 1.0))
    ax = render(Figure(axes=[Axes(artists=[plain, arrow])]), data).axes[0]
    first, second = ax.texts
    assert first.get_text() == "peak" and first.xycoords == "axes fraction"
    assert first.arrow_patch is None
    assert second.xy == (5.0, 1.0) and second.xyann == (2.0, 0.5)
    assert second.arrow_patch is not None and second.get_gid() == arrow.id


def test_a_right_y_axis_takes_its_plots(data, ref) -> None:
    left = LinePlot(x=ref("t"), y=ref("U"), label="U")
    right = LinePlot(x=ref("t"), y=ref("dU"), axis="right", label="dU")
    axes = Axes(
        y=AxisSpec(label="U"),
        y_right=AxisSpec(label="dU", unit="V", scale="log"),
        legend=Legend(visible=True),
        artists=[left, right],
    )
    fig = render(Figure(axes=[axes]), data)
    host, twin = fig.axes
    assert twin.get_gid() == f"{axes.id}#right"
    assert [line.get_gid() for line in host.get_lines()] == [left.id]
    assert [line.get_gid() for line in twin.get_lines()] == [right.id]
    assert twin.get_ylabel() == "dU (V)" and twin.get_yscale() == "log"
    texts = [t.get_text() for t in host.get_legend().get_texts()]
    assert texts == ["U", "dU"]  # one legend for both axes


def test_a_plot_for_a_missing_right_axis_goes_left(data, ref) -> None:
    lonely = LinePlot(x=ref("t"), y=ref("U"), axis="right")
    (ax,) = render(Figure(axes=[Axes(artists=[lonely])]), data).axes
    assert ax.get_lines()[0].get_gid() == lonely.id


def test_an_inset_is_drawn_inside_its_panel(data) -> None:
    from figscribe.model import Inset

    host = Axes()
    inset = Axes(inset=Inset(parent=host.id, bounds=(0.5, 0.5, 0.4, 0.3)))
    fig = render(Figure(axes=[inset, host]), data)  # the inset may come first
    (ax,) = fig.axes
    (child,) = ax.child_axes
    assert ax.get_gid() == host.id and child.get_gid() == inset.id
    fig.canvas.draw()
    outer, inner = ax.get_position(), child.get_position()
    assert inner.x0 == pytest.approx(outer.x0 + 0.5 * outer.width)
    assert inner.height == pytest.approx(0.3 * outer.height)


def test_font_sizes_tick_steps_and_grid(data) -> None:
    from matplotlib.ticker import AutoMinorLocator, MultipleLocator

    axes = Axes(
        title="T",
        title_size=14,
        grid=True,
        grid_axis="x",
        x=AxisSpec(label="t", label_size=11, major_step=2.0, minor_divisions=4),
        y=AxisSpec(label="U", tick_size=6),
    )
    fig = render(Figure(font_size=7, axes=[axes]), data)
    ax = fig.axes[0]
    assert ax.title.get_fontsize() == 14
    assert ax.xaxis.label.get_fontsize() == 11
    assert ax.yaxis.label.get_fontsize() == 7  # follows the figure's font size
    assert isinstance(ax.xaxis.get_major_locator(), MultipleLocator)
    assert isinstance(ax.xaxis.get_minor_locator(), AutoMinorLocator)
    assert ax.yaxis.get_ticklabels()[0].get_fontsize() == 6
    assert ax.xaxis.get_gridlines()[0].get_visible()
    assert not ax.yaxis.get_gridlines()[0].get_visible()


def test_an_untitled_size_keeps_matplotlibs_defaults(data) -> None:
    fig = render(Figure(axes=[Axes(title="T", x=AxisSpec(label="t"))]), data)
    ax = fig.axes[0]
    assert ax.title.get_fontsize() > ax.xaxis.label.get_fontsize()  # "large"
