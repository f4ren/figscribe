"""Renderer: model -> Matplotlib figure, checked structurally.

Pixel-level checks live in test_images.py; these tests assert that each model
field reaches the right Matplotlib property.
"""

from __future__ import annotations

import io
import time

import matplotlib
import matplotlib.colors
import numpy as np
import pytest
from matplotlib.collections import PathCollection
from matplotlib.ticker import MultipleLocator

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


def test_errorbar_line_and_bars_have_their_own_widths(data, ref) -> None:
    bars = ErrorbarPlot(
        x=ref("t"), y=ref("U"), yerr=ref("dU"), linestyle="-", linewidth=3.0
    )
    ax = render(Figure(axes=[Axes(artists=[bars])]), data).axes[0]
    (container,) = ax.containers
    data_line, _, (bar_lines,) = container.lines
    assert data_line.get_linewidth() == 3.0
    assert list(bar_lines.get_linewidths()) == [1.0]  # elinewidth, as before


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


def test_columns_of_unequal_length_are_a_data_error(ref) -> None:
    from figscribe.io import DataError

    columns = {"t": np.arange(4.0), "U": np.arange(3.0)}
    axes = Axes(artists=[LinePlot(x=ref("t"), y=ref("U"))])
    with pytest.raises(DataError, match=r"y \(U\) has 3 values, x \(t\) has 4"):
        render(Figure(axes=[axes]), lambda r: columns[r.column])


def test_share_all_joins_every_axes(data) -> None:
    figure = Figure(
        layout=GridLayout(rows=1, cols=2, share_y="all"),
        axes=[Axes(col=0), Axes(col=1)],
    )
    a, b = render(figure, data).axes
    assert a.get_shared_y_axes().joined(a, b)


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


def test_a_note_has_no_box_unless_it_has_a_background(data) -> None:
    plain = Annotation(text="peak", position=(0.1, 0.9), coords="axes")
    boxed = Annotation(
        text="peak", position=(0.5, 0.5), coords="axes", background="white"
    )
    ax = render(Figure(axes=[Axes(artists=[plain, boxed])]), data).axes[0]
    first, second = ax.texts
    assert first.get_bbox_patch() is None
    patch = second.get_bbox_patch()
    assert patch is not None
    assert matplotlib.colors.same_color(patch.get_facecolor(), "white")
    assert patch.get_edgecolor()[3] == 0.0  # no frame


def test_a_note_with_an_arrow_can_have_a_background(data) -> None:
    note = Annotation(
        text="here", position=(2.0, 0.5), arrow_to=(5.0, 1.0), background="yellow"
    )
    (text,) = render(Figure(axes=[Axes(artists=[note])]), data).axes[0].texts
    assert text.arrow_patch is not None
    assert matplotlib.colors.same_color(text.get_bbox_patch().get_facecolor(), "yellow")


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


def test_an_image_with_a_colour_bar(source) -> None:
    from figscribe.model import ArrayRef, Colorbar, ImagePlot

    table = np.arange(12.0).reshape(3, 4)
    image = ImagePlot(
        data=ArrayRef(source=source.id),
        cmap="magma",
        norm="log",
        vmin=1.0,
        vmax=10.0,
        origin="lower",
        extent=(0.0, 4.0, 0.0, 3.0),
        colorbar=Colorbar(label="counts"),
    )
    fig = render(Figure(axes=[Axes(artists=[image])]), lambda ref: table)
    ax, bar = fig.axes
    (shown,) = ax.get_images()
    assert shown.get_gid() == image.id and shown.get_cmap().name == "magma"
    assert shown.norm.vmin == 1.0 and type(shown.norm).__name__ == "LogNorm"
    assert shown.origin == "lower" and tuple(shown.get_extent()) == (0, 4, 0, 3)
    assert bar.get_ylabel() == "counts" and bar.get_gid() == image.id


def test_a_colour_mesh_on_its_grid(source) -> None:
    from figscribe.model import ArrayRef, ColorMesh, ColumnRef

    values = {"x": np.array([0.0, 1.0, 3.0]), "y": np.array([0.0, 2.0])}

    def data(ref):
        if isinstance(ref, ArrayRef):
            return np.ones((2, 3))
        return values[ref.column]

    mesh = ColorMesh(
        c=ArrayRef(source=source.id),
        x=ColumnRef(source=source.id, column="x"),
        y=ColumnRef(source=source.id, column="y"),
        vmax=2.0,
    )
    (ax,) = render(Figure(axes=[Axes(artists=[mesh])]), data).axes
    (quad,) = ax.collections
    assert quad.get_gid() == mesh.id and quad.norm.vmax == 2.0
    assert ax.dataLim.x1 > 3.0  # cells around the given centres


def test_tick_style_and_prefixes(data, ref) -> None:
    from figscribe.model import Axes, AxisSpec, Figure, LinePlot
    from figscribe.render import render

    axes = Axes(
        x=AxisSpec(label="f", unit="Hz", prefix="k", limits=(0, 225e3)),
        y=AxisSpec(
            label="A",
            scale="log",
            limits=(1300, 1400),
            major_step=50,
            minor_divisions=5,
        ),
        artists=[LinePlot(x=ref("t"), y=ref("U"))],
    )
    figure = Figure(tick_direction="in", ticks_all_sides=True, axes=[axes])
    fig = render(figure, data)
    ax = fig.axes[0]
    fig.canvas.draw()
    assert ax.get_xlabel() == "f (kHz)"
    labels = [t.get_text() for t in ax.get_xticklabels() if t.get_text()]
    assert labels[:3] == ["0", "50", "100"]
    assert list(ax.get_yticks()) == [1250, 1300, 1350, 1400, 1450]
    assert [t.get_text() for t in ax.get_yticklabels()][1:4] == ["1300", "1350", "1400"]
    minor = ax.yaxis.get_minorticklocs()
    assert any(abs(m - 1310) < 1e-6 for m in minor)  # four between 1300 and 1350
    tick = ax.xaxis.get_major_ticks()[1]
    assert tick.tick2line.get_visible()  # on the top edge too
    assert not tick.label2.get_visible()  # but numbers only at the bottom
    assert tick._tickdir == "in"


def test_frame_ticks_and_grid_lines_have_widths(data, ref) -> None:
    axes = Axes(
        grid=True,
        grid_linewidth=0.4,
        grid_linestyle=":",
        artists=[LinePlot(x=ref("t"), y=ref("U"))],
    )
    figure = Figure(
        frame_width=1.2,
        tick_width=1.0,
        tick_length=5.0,
        minor_tick_width=0.7,
        minor_tick_length=2.5,
        axes=[axes],
    )
    fig = render(figure, data)
    fig.canvas.draw()
    ax = fig.axes[0]
    assert {spine.get_linewidth() for spine in ax.spines.values()} == {1.2}
    major = ax.xaxis.get_major_ticks()[0].tick1line
    minor = ax.yaxis.get_minor_ticks()[0].tick1line
    assert (major.get_markeredgewidth(), major.get_markersize()) == (1.0, 5.0)
    assert (minor.get_markeredgewidth(), minor.get_markersize()) == (0.7, 2.5)
    line = ax.xaxis.get_major_ticks()[0].gridline
    assert (line.get_linewidth(), line.get_linestyle()) == (0.4, ":")


DRAW_LIMIT = 5.0
"""Seconds a figure may take to draw here: the freeze it guards against took
over 20 s, while a limit of 1 s failed now and then in a parallel run on a
loaded machine."""


def _drawn(fig) -> float:
    """Seconds to draw `fig` as the preview does, ticks and all."""
    start = time.perf_counter()
    fig.savefig(io.BytesIO(), format="png")
    return time.perf_counter() - start


def test_a_tick_step_far_too_small_falls_back_to_automatic_ticks(data) -> None:
    # Every 1 from 0 to 10 000 took over 20 s per redraw (roadmap B1).
    axes = Axes(x=AxisSpec(limits=(0.0, 10_000.0), major_step=1.0))
    fig = render(Figure(axes=[axes]), data)
    assert _drawn(fig) < DRAW_LIMIT
    ax = fig.axes[0]
    assert not isinstance(ax.xaxis.get_major_locator(), MultipleLocator)


def test_the_tick_limit_applies_to_an_automatic_range(data) -> None:
    # The data run from 0 to 10; the range is not fixed.
    fig = render(Figure(axes=[Axes(x=AxisSpec(major_step=0.001))]), data)
    assert _drawn(fig) < DRAW_LIMIT
    assert not isinstance(fig.axes[0].xaxis.get_major_locator(), MultipleLocator)


def test_a_view_is_shown_and_its_ticks_fit_it(data) -> None:
    # Every 0.01 fits the panel's range of 0 to 0.4, not the view of 0 to 10.
    axes = Axes(x=AxisSpec(limits=(0.0, 0.4), major_step=0.01))
    fig = render(Figure(axes=[axes]), data, view={axes.id: ((0.0, 10.0), (0.0, 1.0))})
    ax = fig.axes[0]
    assert ax.get_xlim() == (0.0, 10.0)
    assert not isinstance(ax.xaxis.get_major_locator(), MultipleLocator)


def test_too_many_minor_ticks_keep_the_major_step(data) -> None:
    # 41 major ticks are fine; ten parts between each give 400 minor ticks.
    axes = Axes(x=AxisSpec(limits=(0.0, 40.0), major_step=1.0, minor_divisions=10))
    fig = render(Figure(axes=[axes]), data)
    ax = fig.axes[0]
    fig.canvas.draw()
    assert np.allclose(np.diff(ax.get_xticks()), 1.0)
    assert len(ax.xaxis.get_minorticklocs()) <= 250


def test_a_tick_step_that_fits_is_kept(data) -> None:
    axes = Axes(x=AxisSpec(limits=(0.0, 40.0), major_step=1.0, minor_divisions=5))
    fig = render(Figure(axes=[axes]), data)
    ax = fig.axes[0]
    fig.canvas.draw()
    assert isinstance(ax.xaxis.get_major_locator(), MultipleLocator)
    assert len(ax.xaxis.get_minorticklocs()) == 40 * 4  # four between each pair


@pytest.mark.parametrize(
    ("fit_range", "extend", "span"),
    [
        (None, False, (0.0, 10.0)),
        ((2.0, 7.0), False, (2.0, 7.0)),
        ((2.0, 7.0), True, (0.0, 10.0)),
        ((-5.0, 4.0), False, (0.0, 4.0)),  # no curve where there is no data
    ],
)
def test_a_fit_is_drawn_over_its_range(data, ref, fit_range, extend, span) -> None:
    from figscribe.model import FitCurve, FitResult, PredefinedFit, ResidualPlot

    points = ErrorbarPlot(x=ref("t"), y=ref("U"), yerr=ref("dU"))
    fit = FitCurve(
        target=points.id,
        model=PredefinedFit(name="linear"),
        fit_range=fit_range,
        extend_curve=extend,
        result=FitResult(parameters={"a": 0.1, "b": 0.0}, uncertainties={}),
    )
    residuals = ResidualPlot(target=fit.id)
    figure = Figure(
        layout=GridLayout(rows=2),
        axes=[Axes(artists=[points, fit]), Axes(row=1, artists=[residuals])],
    )
    drawn = render(figure, data)
    [curve] = [a for a in drawn.axes[0].lines if a.get_gid() == fit.id]
    assert (curve.get_xdata().min(), curve.get_xdata().max()) == span
    [shown] = [a for a in drawn.axes[1].lines if a.get_gid() == residuals.id]
    low, high = fit_range or (0.0, 10.0)
    assert shown.get_xdata().min() >= low and shown.get_xdata().max() <= high


def _letters(fig) -> dict[str, list]:
    """The panel labels drawn, by the gid of their axes."""
    from matplotlib.text import Annotation as MplAnnotation

    return {
        ax.get_gid(): [t for t in ax.texts if isinstance(t, MplAnnotation)]
        for ax in fig.findobj(lambda a: hasattr(a, "texts") and a.get_gid())
    }


def test_panel_labels_are_drawn_on_each_panel_but_not_on_insets(data) -> None:
    from figscribe.model import Inset, PanelLabels

    left, right = Axes(), Axes(col=1)
    inset = Axes(inset=Inset(parent=left.id))
    figure = Figure(layout=GridLayout(cols=2), axes=[left, right, inset])
    assert all(texts == [] for texts in _letters(render(figure, data)).values())
    figure.panel_labels = PanelLabels()
    drawn = _letters(render(figure, data))
    assert [t.get_text() for t in drawn[left.id]] == ["(a)"]
    assert [t.get_text() for t in drawn[right.id]] == ["(b)"]
    assert drawn[inset.id] == []
    (label,) = drawn[left.id]
    # Outside the top left corner, not a note: no gid, so it cannot be dragged.
    assert label.xy == (0, 1) and label.xycoords == "axes fraction"
    assert (label.get_ha(), label.get_va()) == ("right", "bottom")
    assert label.get_gid() is None
    assert label.get_fontweight() == "normal"


def test_panel_labels_inside_bold_and_sized(data) -> None:
    from figscribe.model import PanelLabels

    figure = Figure(
        axes=[Axes()],
        panel_labels=PanelLabels(placement="inside", bold=True, fontsize=14.0),
    )
    fig = render(figure, data)
    ((label,),) = _letters(fig).values()
    assert (label.get_ha(), label.get_va()) == ("left", "top")
    assert label.get_fontweight() == "bold" and label.get_fontsize() == 14.0
    fig.draw_without_rendering()  # lays the panels out
    box, frame = label.get_window_extent(), fig.axes[0].bbox
    assert frame.x0 < box.x0 and box.y1 < frame.y1  # inside the corner


def test_an_outside_panel_label_gets_room_from_the_layout(data) -> None:
    from figscribe.model import PanelLabels

    figure = Figure(axes=[Axes()], panel_labels=PanelLabels(fontsize=20.0))
    fig = render(figure, data)
    fig.draw_without_rendering()  # lays the panels out
    ((label,),) = _letters(fig).values()
    box = label.get_window_extent()
    assert box.x0 >= 0 and box.y1 <= fig.bbox.y1


def test_reference_lines_span_the_panel(data, ref) -> None:
    from figscribe.model import ReferenceLine

    vertical = ReferenceLine(at=4.0, label="onset")
    horizontal = ReferenceLine(
        orientation="horizontal", at=0.5, color="C3", linestyle=":", linewidth=2.0
    )
    axes = Axes(
        legend=Legend(visible=True),
        artists=[LinePlot(x=ref("t"), y=ref("U")), vertical, horizontal],
    )
    fig = render(Figure(axes=[axes]), data)
    ax = fig.axes[0]
    drawn = {line.get_gid(): line for line in ax.lines}
    v, h = drawn[vertical.id], drawn[horizontal.id]
    assert list(v.get_xdata()) == [4.0, 4.0] and list(v.get_ydata()) == [0, 1]
    assert list(h.get_ydata()) == [0.5, 0.5] and list(h.get_xdata()) == [0, 1]
    assert (v.get_color(), v.get_linestyle(), v.get_linewidth()) == ("gray", "--", 1.0)
    assert (h.get_color(), h.get_linestyle(), h.get_linewidth()) == ("C3", ":", 2.0)
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["onset"]


def test_shaded_spans_lie_behind_the_data(data, ref) -> None:
    from figscribe.model import ShadedSpan

    band = ShadedSpan(start=3.0, end=6.0, label="pulse")
    across = ShadedSpan(orientation="horizontal", start=0.2, end=0.4, color="C2")
    axes = Axes(artists=[LinePlot(x=ref("t"), y=ref("U")), band, across])
    fig = render(Figure(axes=[axes]), data)
    ax = fig.axes[0]
    patches = {p.get_gid(): p for p in ax.patches}
    shaded, flat = patches[band.id], patches[across.id]
    assert shaded.get_zorder() == 0.5 < ax.lines[0].get_zorder()
    assert shaded.get_alpha() == 0.2 and shaded.get_linewidth() == 0

    def corners(patch):
        return patch.get_patch_transform().transform(patch.get_path().vertices)

    assert {round(x, 9) for x, _ in corners(shaded)} == {3.0, 6.0}
    assert {round(y, 9) for _, y in corners(flat)} == {0.2, 0.4}


def test_a_horizontal_line_goes_with_the_right_axis(data, ref) -> None:
    from figscribe.model import ReferenceLine

    line = ReferenceLine(orientation="horizontal", at=50.0, axis="right")
    axes = Axes(
        y_right=AxisSpec(limits=(0.0, 100.0)),
        artists=[LinePlot(x=ref("t"), y=ref("U")), line],
    )
    fig = render(Figure(axes=[axes]), data)
    right = next(ax for ax in fig.axes if ax.get_gid().endswith("#right"))
    assert [ln.get_gid() for ln in right.lines] == [line.id]


def test_an_error_band_takes_the_place_of_the_y_error_bars(data, columns, ref) -> None:
    from matplotlib.colors import to_rgba

    from figscribe.model import ErrorBand

    plot = ErrorbarPlot(
        x=ref("t"), y=ref("U"), yerr=ref("dU"), linestyle="-", band=ErrorBand()
    )
    ax = render(Figure(axes=[Axes(artists=[plot])]), data).axes[0]
    assert not ax.containers  # without x errors, a plain line
    (line,) = ax.lines
    (band,) = ax.collections
    assert line.get_gid() == band.get_gid() == plot.id
    assert band.get_zorder() < line.get_zorder()  # behind the line
    assert tuple(band.get_facecolor()[0]) == to_rgba(line.get_color(), 0.25)
    (path,) = band.get_paths()
    low, high = path.vertices[:, 1].min(), path.vertices[:, 1].max()
    assert low == pytest.approx((columns["U"] - 0.05).min())
    assert high == pytest.approx((columns["U"] + 0.05).max())
    assert band.get_label() == "_nolegend_"


def test_an_error_band_keeps_the_x_errors_as_bars(data, ref) -> None:
    from figscribe.model import ErrorBand

    plot = ErrorbarPlot(
        x=ref("t"),
        y=ref("U"),
        xerr=ref("dU"),
        yerr=ref("dU"),
        color="C3",
        band=ErrorBand(color="0.5", alpha=0.5),
        alpha=0.8,
    )
    ax = render(Figure(axes=[Axes(artists=[plot])]), data).axes[0]
    (container,) = ax.containers
    assert container.has_xerr and not container.has_yerr
    (band,) = ax.collections[-1:]
    assert band.get_alpha() == pytest.approx(0.4)  # the band's, times the plot's
    assert tuple(band.get_facecolor()[0])[:3] == (0.5, 0.5, 0.5)


def test_an_error_band_leaves_a_gap_at_left_out_rows(data, ref) -> None:
    from figscribe.model import ErrorBand

    plot = ErrorbarPlot(
        x=ref("t"),
        y=ref("U"),
        yerr=ref("dU"),
        marker="s",
        left_out=[5],
        band=ErrorBand(),
    )
    ax = render(Figure(axes=[Axes(artists=[plot])]), data).axes[0]
    (band,) = ax.collections
    assert len(band.get_paths()) == 2  # before and after the left-out row
    kept, out = ax.lines
    assert out.get_marker() == "s" and list(out.get_xdata()) == [2.5]
    assert not ax.containers  # the left-out point has no error bar either


def test_an_error_band_without_y_errors_draws_nothing_more(data, ref) -> None:
    from figscribe.model import ErrorBand

    plot = ErrorbarPlot(x=ref("t"), y=ref("U"), band=ErrorBand())
    ax = render(Figure(axes=[Axes(artists=[plot])]), data).axes[0]
    assert not ax.collections and len(ax.lines) == 1


def test_a_mesh_numbers_its_cells_along_an_axis_without_positions() -> None:
    from figscribe.model import ArrayRef, ColorMesh, ColumnRef

    grid = np.arange(12.0).reshape(3, 4)
    columns = {"x": np.array([0.0, 1.0, 3.0, 7.0]), "short": np.arange(2.0)}

    def data(ref):
        return grid if isinstance(ref, ArrayRef) else columns[ref.column]

    mesh = ColorMesh(c=ArrayRef(source="s"), x=ColumnRef(source="s", column="x"))
    fig = render(Figure(axes=[Axes(artists=[mesh])]), data)
    fig.canvas.draw()
    assert fig.axes[0].get_ylim() == pytest.approx((-0.5, 2.5))  # rows 0, 1, 2

    from figscribe.io import DataError

    mesh.x = ColumnRef(source="s", column="short")
    with pytest.raises(DataError, match="4 cells along x, but 2 x positions"):
        render(Figure(axes=[Axes(artists=[mesh])]), data)


def test_an_image_of_a_single_column_is_refused_in_words() -> None:
    from figscribe.io import DataError
    from figscribe.model import ArrayRef, ImagePlot

    image = ImagePlot(data=ArrayRef(source="s"))
    with pytest.raises(DataError, match="needs 2-D data"):
        render(Figure(axes=[Axes(artists=[image])]), lambda ref: np.arange(5.0))
