"""Model -> Matplotlib figure, for the GUI preview and for export alike.

Builds a `matplotlib.figure.Figure` directly instead of going through pyplot,
so rendering touches no global figure state and needs no GUI backend.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext

import matplotlib.style
import numpy as np
from matplotlib.axes import Axes as MplAxes
from matplotlib.figure import Figure as MplFigure

from figscribe.model import (
    Artist,
    Axes,
    AxisSpec,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    Legend,
    LinePlot,
    ScatterPlot,
)
from figscribe.render.labels import axis_label

DataProvider = Callable[[ColumnRef], np.ndarray]
"""Resolves a column reference to its values; loading files is not our job."""

MM_PER_INCH = 25.4


def render(figure: Figure, data: DataProvider) -> MplFigure:
    """Build the Matplotlib figure for `figure`.

    Every drawn artist gets its model id as gid, so the GUI can map a click on
    a Matplotlib artist back to the model object.
    """
    with style_context(figure):
        fig = MplFigure(
            figsize=(figure.width_mm / MM_PER_INCH, figure.height_mm / MM_PER_INCH),
            dpi=figure.dpi,
            layout="constrained" if figure.layout.constrained_layout else None,
        )
        layout = figure.layout
        grid = fig.add_gridspec(
            layout.rows,
            layout.cols,
            width_ratios=layout.width_ratios,
            height_ratios=layout.height_ratios,
            hspace=layout.hspace,
            wspace=layout.wspace,
        )

        drawn: list[tuple[Axes, MplAxes]] = []
        for axes in figure.axes:
            ax = fig.add_subplot(
                grid[
                    axes.row : axes.row + axes.rowspan,
                    axes.col : axes.col + axes.colspan,
                ],
                sharex=_share_partner(axes, drawn, layout.share_x, "col"),
                sharey=_share_partner(axes, drawn, layout.share_y, "row"),
            )
            ax.set_gid(axes.id)
            _draw_axes(axes, ax, data, figure.unit_format)
            drawn.append((axes, ax))

        _hide_inner_tick_labels([ax for _, ax in drawn])
    return fig


def _hide_inner_tick_labels(axs: list[MplAxes]) -> None:
    """Hide tick labels that a sharing partner already shows: x labels when a
    partner lies below in an overlapping column, y labels when one lies to the
    left in an overlapping row.

    Not plt.subplots' rule of "only the bottom row and left column": in a grid
    with gaps or spans, that strips labels from an axes with no partner below,
    and its column ends up with no x tick labels at all.
    """
    for ax in axs:
        spec = ax.get_subplotspec()
        for partner in ax.get_shared_x_axes().get_siblings(ax):
            other = partner.get_subplotspec()
            below = other.rowspan.start >= spec.rowspan.stop
            if below and not set(other.colspan).isdisjoint(spec.colspan):
                ax.xaxis.set_tick_params(which="both", labelbottom=False)
                break
        for partner in ax.get_shared_y_axes().get_siblings(ax):
            other = partner.get_subplotspec()
            left = other.colspan.stop <= spec.colspan.start
            if left and not set(other.rowspan).isdisjoint(spec.rowspan):
                ax.yaxis.set_tick_params(which="both", labelleft=False)
                break


def style_context(figure: Figure):
    """Apply the figure's stylesheet while the figure is built."""
    if figure.stylesheet is None:
        return nullcontext()
    return matplotlib.style.context(figure.stylesheet)


def _share_partner(
    axes: Axes, drawn: list[tuple[Axes, MplAxes]], mode: str, along: str
) -> MplAxes | None:
    """Return the axes to share with: the first one, or the first in the same
    column ("col") or row ("row"), counted by where an axes starts."""
    if mode == "none":
        return None
    for other, ax in drawn:
        if mode == "all" or getattr(other, along) == getattr(axes, along):
            return ax
    return None


def _draw_axes(axes: Axes, ax: MplAxes, data: DataProvider, unit_format: str) -> None:
    if axes.y_right is not None:
        raise NotImplementedError("a right-hand y-axis (y_right) is planned for M5")

    if axes.title is not None:
        ax.set_title(axes.title)
    _apply_axis(ax, "x", axes.x, unit_format)
    _apply_axis(ax, "y", axes.y, unit_format)
    if axes.grid:
        ax.grid(True)

    for artist in axes.artists:
        _draw_artist(artist, ax, data)

    if axes.legend.visible:
        _draw_legend(axes.legend, ax)


def _apply_axis(ax: MplAxes, name: str, spec: AxisSpec, unit_format: str) -> None:
    axis = ax.xaxis if name == "x" else ax.yaxis
    label = axis_label(spec, unit_format)
    if label is not None:
        axis.set_label_text(label)

    set_scale, set_lim = (
        (ax.set_xscale, ax.set_xlim) if name == "x" else (ax.set_yscale, ax.set_ylim)
    )
    if spec.scale == "symlog" and spec.symlog_linthresh is not None:
        set_scale("symlog", linthresh=spec.symlog_linthresh)
    else:
        set_scale(spec.scale)

    if spec.limits is not None:
        set_lim(*spec.limits)
    if spec.ticks is not None:
        axis.set_ticks(spec.ticks, labels=spec.tick_labels)
    if spec.minor_ticks:
        axis.minorticks_on()
    else:
        axis.minorticks_off()


def _draw_artist(artist: Artist, ax: MplAxes, data: DataProvider) -> None:
    if artist.axis == "right":
        raise NotImplementedError("drawing against y_right is planned for M5")

    common = {
        "label": artist.label if artist.label is not None else "_nolegend_",
        "visible": artist.visible,
        "zorder": artist.zorder,
        "alpha": artist.alpha,
        "gid": artist.id,
    }

    if isinstance(artist, LinePlot):
        ax.plot(
            data(artist.x),
            data(artist.y),
            color=artist.color,
            linestyle=artist.linestyle,
            linewidth=artist.linewidth,
            marker=artist.marker,
            markersize=artist.markersize,
            **common,
        )
    elif isinstance(artist, ScatterPlot):
        ax.scatter(
            data(artist.x),
            data(artist.y),
            s=artist.size,
            color=artist.color,
            marker=artist.marker,
            edgecolors=artist.edgecolor,
            **common,
        )
    elif isinstance(artist, ErrorbarPlot):
        container = ax.errorbar(
            data(artist.x),
            data(artist.y),
            xerr=data(artist.xerr) if artist.xerr is not None else None,
            yerr=data(artist.yerr) if artist.yerr is not None else None,
            color=artist.color,
            linestyle=artist.linestyle,
            marker=artist.marker,
            markersize=artist.markersize,
            capsize=artist.capsize,
            elinewidth=artist.elinewidth,
            **common,
        )
        # A container has no gid of its own; tag every part so a click on a cap
        # or a bar maps back to the artist as well.
        for part in container.get_children():
            part.set_gid(artist.id)
    else:
        raise NotImplementedError(
            f"rendering {artist.kind!r} artists is not implemented yet"
        )


def _draw_legend(legend: Legend, ax: MplAxes) -> None:
    if legend.position is not None:
        # A dragged legend: anchor its lower-left corner at the axes position.
        placement = {"loc": "lower left", "bbox_to_anchor": legend.position}
    else:
        placement = {"loc": legend.location}
    ax.legend(
        frameon=legend.frame,
        ncols=legend.ncols,
        fontsize=legend.fontsize,
        **placement,
    )
