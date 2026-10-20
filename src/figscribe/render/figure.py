"""Model -> Matplotlib figure, for the GUI preview and for export alike.

Builds a `matplotlib.figure.Figure` directly instead of going through pyplot,
so rendering touches no global figure state and needs no GUI backend.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import nullcontext

import matplotlib.style
import numpy as np
from matplotlib.axes import Axes as MplAxes
from matplotlib.figure import Figure as MplFigure
from matplotlib.ticker import AutoMinorLocator, MultipleLocator

from figscribe.model import (
    Annotation,
    Artist,
    Axes,
    AxisSpec,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    FitCurve,
    Histogram,
    Legend,
    LinePlot,
    ResidualPlot,
    ScatterPlot,
)
from figscribe.model.validate import FITTABLE
from figscribe.render.labels import axis_label
from figscribe.render.layout import (
    creation_order,
    hidden_tick_labels,
    inset_parent,
    share_partner,
)

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

        artists = {a.id: a for axes in figure.axes for a in axes.artists}
        axs: dict[int, MplAxes] = {}
        for i in creation_order(figure):
            axes = figure.axes[i]
            if axes.inset is not None:
                host = axs[inset_parent(figure, i)]
                ax = host.inset_axes(list(axes.inset.bounds))
            else:
                partners = [share_partner(figure, i, axis) for axis in ("x", "y")]
                ax = fig.add_subplot(
                    grid[
                        axes.row : axes.row + axes.rowspan,
                        axes.col : axes.col + axes.colspan,
                    ],
                    sharex=axs[partners[0]] if partners[0] is not None else None,
                    sharey=axs[partners[1]] if partners[1] is not None else None,
                )
            ax.set_gid(axes.id)
            _draw_axes(axes, ax, data, figure.unit_format, artists)
            axs[i] = ax

        for i, (hide_x, hide_y) in enumerate(hidden_tick_labels(figure)):
            ax = axs[i]
            if hide_x:
                ax.xaxis.set_tick_params(which="both", labelbottom=False)
            if hide_y:
                ax.yaxis.set_tick_params(which="both", labelleft=False)
    return fig


def style_context(figure: Figure):
    """Apply the figure's style sheet and font size while it is built."""
    styles: list = []
    if figure.stylesheet is not None:
        styles.append(figure.stylesheet)
    if figure.font_size is not None:
        styles.append({"font.size": figure.font_size})
    return matplotlib.style.context(styles) if styles else nullcontext()


def _draw_axes(
    axes: Axes,
    ax: MplAxes,
    data: DataProvider,
    unit_format: str,
    artists: Mapping[str, Artist],
) -> None:
    if axes.y_right is not None:
        raise NotImplementedError("a right-hand y-axis (y_right) is planned for M5")

    if axes.title is not None:
        size = {"fontsize": axes.title_size} if axes.title_size else {}
        ax.set_title(axes.title, **size)
    _apply_axis(ax, "x", axes.x, unit_format)
    _apply_axis(ax, "y", axes.y, unit_format)
    if axes.grid:
        ax.grid(True, which=axes.grid_which, axis=axes.grid_axis)

    for artist in axes.artists:
        _draw_artist(artist, ax, data, artists)

    if axes.legend.visible:
        _draw_legend(axes.legend, ax).set_gid(axes.id)


def _apply_axis(ax: MplAxes, name: str, spec: AxisSpec, unit_format: str) -> None:
    axis = ax.xaxis if name == "x" else ax.yaxis
    label = axis_label(spec, unit_format)
    if label is not None:
        size = {"fontsize": spec.label_size} if spec.label_size else {}
        axis.set_label_text(label, **size)

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
    elif spec.major_step is not None:
        axis.set_major_locator(MultipleLocator(spec.major_step))
    if spec.minor_ticks and spec.minor_divisions is not None:
        axis.set_minor_locator(AutoMinorLocator(spec.minor_divisions))
    elif spec.minor_ticks:
        axis.minorticks_on()
    else:
        axis.minorticks_off()
    if spec.tick_size is not None:
        ax.tick_params(axis=name, which="both", labelsize=spec.tick_size)


def _draw_artist(
    artist: Artist, ax: MplAxes, data: DataProvider, artists: Mapping[str, Artist]
) -> None:
    """Draw one artist; `artists` finds the plots that fits and residuals
    refer to, wherever in the figure they are."""
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
    elif isinstance(artist, Histogram):
        values = np.asarray(data(artist.values), dtype=float)
        # np.histogram cannot place NaN or inf; they are left out, like in a fit.
        _, _, patches = ax.hist(
            values[np.isfinite(values)],
            bins=artist.bins,
            density=artist.density,
            histtype=artist.histtype,
            color=artist.color,
            **common,
        )
        for patch in patches:
            patch.set_gid(artist.id)
    elif isinstance(artist, Annotation):
        _draw_annotation(artist, ax, common)
    elif isinstance(artist, FitCurve):
        _draw_fit(artist, ax, data, artists, common)
    elif isinstance(artist, ResidualPlot):
        _draw_residuals(artist, ax, data, artists, common)
    else:
        raise NotImplementedError(
            f"rendering {artist.kind!r} artists is not implemented yet"
        )


COORDS = {"data": "data", "axes": "axes fraction"}
"""Annotation coordinates, as Matplotlib names them."""


def _draw_annotation(note: Annotation, ax: MplAxes, common: dict) -> None:
    """A note at its position; with `arrow_to`, an arrow from it to there."""
    coords = COORDS[note.coords]
    arrow = {}
    if note.arrow_to is not None:
        props = {"arrowstyle": "->"}
        if note.color is not None:
            props["color"] = note.color
        arrow = {"xytext": note.position, "textcoords": coords, "arrowprops": props}
    # Unset sizes and colours are not passed: None is not the same as the
    # default for every Matplotlib text property.
    style = {
        key: value
        for key, value in (("fontsize", note.fontsize), ("color", note.color))
        if value is not None
    }
    ax.annotate(
        note.text,
        xy=note.arrow_to if note.arrow_to is not None else note.position,
        xycoords=coords,
        **arrow,
        **style,
        **common,
    )


CURVE_POINTS = 400
"""Points along a fitted curve: smooth at any print size."""


def _draw_fit(
    fit: FitCurve,
    ax: MplAxes,
    data: DataProvider,
    artists: Mapping[str, Artist],
    common: dict,
) -> None:
    """The fitted model across the range of its data; nothing before a fit."""
    from figscribe.fit import evaluate

    target = _referenced(artists, fit.target, FITTABLE, "fit")
    if fit.result is None:
        return
    x = np.asarray(data(target.x), dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return
    xs = np.linspace(x.min(), x.max(), CURVE_POINTS)
    ys = evaluate(fit.model, fit.result.parameters, xs)
    ax.plot(
        xs,
        ys,
        color=fit.color,
        linestyle=fit.linestyle,
        linewidth=fit.linewidth,
        **common,
    )


def _draw_residuals(
    residuals: ResidualPlot,
    ax: MplAxes,
    data: DataProvider,
    artists: Mapping[str, Artist],
    common: dict,
) -> None:
    """Data minus fit at every data point, with the data's y errors, around a
    dashed zero line."""
    from figscribe.fit import evaluate

    fit = _referenced(artists, residuals.target, (FitCurve,), "residual plot")
    target = _referenced(artists, fit.target, FITTABLE, "fit")
    ax.axhline(0.0, color="0.6", linewidth=0.8, linestyle="--", zorder=1)
    if fit.result is None:
        return
    x = np.asarray(data(target.x), dtype=float)
    y = np.asarray(data(target.y), dtype=float)
    yerr = (
        data(target.yerr)
        if isinstance(target, ErrorbarPlot) and target.yerr is not None
        else None
    )
    container = ax.errorbar(
        x,
        y - evaluate(fit.model, fit.result.parameters, x),
        yerr=yerr,
        color=residuals.color,
        marker=residuals.marker,
        markersize=residuals.markersize,
        linestyle=residuals.linestyle,
        **common,
    )
    for part in container.get_children():
        part.set_gid(residuals.id)


def _referenced(artists: Mapping[str, Artist], oid: str, kinds: tuple, what: str):
    found = artists.get(oid)
    if not isinstance(found, kinds):
        raise ValueError(f"the {what} refers to {oid!r}, which is not in the figure")
    return found


def _draw_legend(legend: Legend, ax: MplAxes):
    """Draw the legend; it carries its axes' id, so a click on it selects them."""
    if legend.position is not None:
        # A dragged legend: anchor its lower-left corner at the axes position.
        placement = {"loc": "lower left", "bbox_to_anchor": legend.position}
    else:
        placement = {"loc": legend.location}
    return ax.legend(
        frameon=legend.frame,
        ncols=legend.ncols,
        fontsize=legend.fontsize,
        **placement,
    )
