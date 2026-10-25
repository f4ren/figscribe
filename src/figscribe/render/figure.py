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
from matplotlib.colors import LogNorm
from matplotlib.figure import Figure as MplFigure
from matplotlib.ticker import (
    AutoMinorLocator,
    FuncFormatter,
    MultipleLocator,
    NullFormatter,
)

from figscribe.io.errors import DataError
from figscribe.model import (
    Annotation,
    ArrayRef,
    Artist,
    Axes,
    AxisSpec,
    ColorMesh,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    FitCurve,
    Histogram,
    ImagePlot,
    Legend,
    LinePlot,
    ResidualPlot,
    ScatterPlot,
)
from figscribe.model.validate import FITTABLE, unequal_columns
from figscribe.render.labels import axis_label
from figscribe.render.layout import (
    creation_order,
    hidden_tick_labels,
    inset_parent,
    share_partner,
)
from figscribe.render.ticks import (
    minor_ticks,
    scaling,
    shown,
    silent_minor_labels,
    tick_style,
    ticks_that_fit,
)

DataProvider = Callable[[ColumnRef | ArrayRef], np.ndarray]
"""Resolves a column (1-D) or array (2-D) reference to its values; loading
files is not our job."""

MM_PER_INCH = 25.4

View = Mapping[str, tuple[tuple[float, float], tuple[float, float]]]
"""Ranges (x, y) by the gid of a Matplotlib axes."""
RIGHT = "#right"
"""Appended to an axes id to name the Matplotlib axes of its right y axis."""


def render(figure: Figure, data: DataProvider, view: View | None = None) -> MplFigure:
    """Build the Matplotlib figure for `figure`.

    Every drawn artist gets its model id as gid, so the GUI can map a click on
    a Matplotlib artist back to the model object. `view` shows some axes, by
    gid, at other ranges than the model's, as the preview does while zoomed.
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
        ticked: list[tuple[MplAxes, str, AxisSpec]] = []
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
            ticked += _draw_axes(axes, ax, data, figure.unit_format, artists)
            axs[i] = ax

        # Only now are the automatic ranges known that decide whether a tick
        # step fits. A style with axes.autolimit_mode "round_numbers" rounds
        # the range to the ticks, so there it is worked out again with the new
        # ones, as the script does when it draws. Elsewhere it must not be:
        # done early, it gives empty panels another range than drawing does.
        for ax, _, _ in ticked:
            if view and ax.get_gid() in view:
                xlim, ylim = view[ax.get_gid()]
                ax.set_xlim(xlim)
                ax.set_ylim(ylim)
        rounded = matplotlib.rcParams["axes.autolimit_mode"] == "round_numbers"
        for ax, name, spec in ticked:
            interval = ax.get_xlim() if name == "x" else ax.get_ylim()
            _apply_ticks(ax, name, ticks_that_fit(spec, interval))
            if rounded:
                ax.autoscale_view(scalex=name == "x", scaley=name == "y")

        for i, (hide_x, hide_y) in enumerate(hidden_tick_labels(figure)):
            ax = axs[i]
            if hide_x:
                ax.xaxis.set_tick_params(which="both", labelbottom=False)
            if hide_y:
                ax.yaxis.set_tick_params(which="both", labelleft=False)
    return fig


def tick_ranges(
    figure: Figure, data: DataProvider | None
) -> dict[tuple[str, str], tuple[float, float]]:
    """The range of each axis with its own tick step or divisions, by
    (Axes.id, "x", "y" or "y_right"): what the renderer counts ticks over.

    An automatic range is only known by drawing, so the figure is drawn when
    there is one and `data` is given; without data such axes are left out.
    """
    specs = {
        (axes.id, field): spec
        for axes in figure.axes
        for field in ("x", "y", "y_right")
        if (spec := getattr(axes, field)) is not None
        and (spec.major_step is not None or spec.minor_divisions is not None)
    }
    ranges = {key: s.limits for key, s in specs.items() if s.limits is not None}
    if len(ranges) == len(specs) or data is None:
        return ranges
    for ax in render(figure, data).findobj(MplAxes):
        gid = ax.get_gid()
        if gid is None:
            continue
        if gid.endswith(RIGHT):
            drawn = {(gid.removesuffix(RIGHT), "y_right"): ax.get_ylim()}
        else:
            drawn = {(gid, "x"): ax.get_xlim(), (gid, "y"): ax.get_ylim()}
        ranges.update({key: r for key, r in drawn.items() if key in specs})
    return ranges


def style_context(figure: Figure):
    """Apply the figure's style sheet and font size while it is built."""
    styles: list = []
    if figure.stylesheet is not None:
        styles.append(figure.stylesheet)
    if figure.font_size is not None:
        styles.append({"font.size": figure.font_size})
    if tick_style(figure):
        styles.append(tick_style(figure))
    return matplotlib.style.context(styles) if styles else nullcontext()


def _draw_axes(
    axes: Axes,
    ax: MplAxes,
    data: DataProvider,
    unit_format: str,
    artists: Mapping[str, Artist],
) -> list[tuple[MplAxes, str, AxisSpec]]:
    """Draw one panel; returns its axes whose ticks are still to be placed."""
    if axes.title is not None:
        size = {"fontsize": axes.title_size} if axes.title_size else {}
        ax.set_title(axes.title, **size)
    _apply_axis(ax, "x", axes.x, unit_format)
    _apply_axis(ax, "y", axes.y, unit_format)
    right = None
    if axes.y_right is not None:
        right = ax.twinx()
        right.set_gid(f"{axes.id}{RIGHT}")
        _apply_axis(right, "y", axes.y_right, unit_format)
    if axes.grid:
        color = {"color": axes.grid_color} if axes.grid_color else {}
        ax.grid(True, which=axes.grid_which, axis=axes.grid_axis, **color)

    for artist in axes.artists:
        # Without a right axis, a plot meant for it is drawn against the left
        # one; validate_references reports it.
        target = right if artist.axis == "right" and right is not None else ax
        _draw_artist(artist, target, data, artists)

    if axes.legend.visible:
        _draw_legend(axes.legend, ax, right).set_gid(axes.id)

    ticked = [(ax, "x", axes.x), (ax, "y", axes.y)]
    if axes.y_right is not None:
        ticked.append((right, "y", axes.y_right))
    return ticked


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


def _apply_ticks(ax: MplAxes, name: str, spec: AxisSpec) -> None:
    """The tick step, minor ticks and tick numbers, once the range is known."""
    axis = ax.xaxis if name == "x" else ax.yaxis
    if spec.ticks is None and spec.major_step is not None:
        axis.set_major_locator(MultipleLocator(spec.major_step))
    how, value = minor_ticks(spec)
    if how == "parts":
        axis.set_minor_locator(AutoMinorLocator(value))
    elif how == "step":
        axis.set_minor_locator(MultipleLocator(value))
    elif how == "on":
        axis.minorticks_on()
    else:
        axis.minorticks_off()
    scaled = scaling(spec)
    if scaled is not None:
        axis.set_major_formatter(FuncFormatter(lambda v, _: shown(v, scaled)))
    if silent_minor_labels(spec):
        axis.set_minor_formatter(NullFormatter())
    if spec.tick_size is not None:
        ax.tick_params(axis=name, which="both", labelsize=spec.tick_size)


def _draw_artist(
    artist: Artist, ax: MplAxes, data: DataProvider, artists: Mapping[str, Artist]
) -> None:
    """Draw one artist; `artists` finds the plots that fits and residuals
    refer to, wherever in the figure they are."""
    common = {
        "label": artist.label if artist.label is not None else "_nolegend_",
        "visible": artist.visible,
        "zorder": artist.zorder,
        "alpha": artist.alpha,
        "gid": artist.id,
    }
    # Matplotlib would say "x and y must have same first dimension".
    if isinstance(artist, FITTABLE) and (why := unequal_columns(artist, data)):
        raise DataError(f"{artist.label or artist.kind}: {why}")

    if isinstance(artist, FITTABLE):
        _draw_points(artist, ax, data, common)
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
    elif isinstance(artist, ImagePlot | ColorMesh):
        _draw_2d(artist, ax, data, common)
    elif isinstance(artist, FitCurve):
        _draw_fit(artist, ax, data, artists, common)
    elif isinstance(artist, ResidualPlot):
        _draw_residuals(artist, ax, data, artists, common)
    else:
        raise NotImplementedError(
            f"rendering {artist.kind!r} artists is not implemented yet"
        )


LEFT_OUT_COLOR = "0.7"
"""Light grey: left-out points stay visible, but stand back."""


def _draw_points(artist, ax: MplAxes, data: DataProvider, common: dict) -> None:
    """A line, scatter or error bar plot: the kept points as styled, then the
    left-out ones apart in their own color, without a legend entry. Each
    drawn part carries `rows`, the data rows it shows, for clicks."""
    from figscribe.fit import FitError, kept

    columns = {
        name: np.asarray(data(ref), dtype=float)
        for name in ("x", "y", "xerr", "yerr")
        if (ref := getattr(artist, name, None)) is not None
    }
    count = len(columns["x"])
    try:
        shown = kept(count, artist.left_out)
    except FitError as exc:
        raise DataError(f"{artist.label or artist.kind}: {exc}") from None
    parts = [(shown, {}, common)]
    if artist.left_out:
        apart = {
            "color": artist.left_out_color or LEFT_OUT_COLOR,
            "marker": artist.left_out_marker or getattr(artist, "marker", None) or "o",
        }
        parts.append((~shown, apart, {**common, "label": "_nolegend_"}))
    for rows, style, options in parts:
        values = {name: column[rows] for name, column in columns.items()}
        if isinstance(artist, LinePlot):
            drawn = ax.plot(
                values["x"],
                values["y"],
                color=style.get("color", artist.color),
                linestyle="none" if style else artist.linestyle,
                linewidth=artist.linewidth,
                marker=style.get("marker", artist.marker),
                markersize=artist.markersize,
                **options,
            )[0]
        elif isinstance(artist, ScatterPlot):
            drawn = ax.scatter(
                values["x"],
                values["y"],
                s=artist.size,
                color=style.get("color", artist.color),
                marker=style.get("marker", artist.marker),
                edgecolors=artist.edgecolor,
                **options,
            )
        else:
            container = ax.errorbar(
                values["x"],
                values["y"],
                xerr=values.get("xerr"),
                yerr=values.get("yerr"),
                color=style.get("color", artist.color),
                linestyle="none" if style else artist.linestyle,
                marker=style.get("marker", artist.marker),
                markersize=artist.markersize,
                capsize=artist.capsize,
                elinewidth=artist.elinewidth,
                **options,
            )
            # A container has no gid of its own; tag every part so a click on
            # a cap or a bar maps back to the artist as well.
            for part in container.get_children():
                part.set_gid(artist.id)
            drawn = container.lines[0]
        drawn.rows = np.flatnonzero(rows)


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


def _draw_2d(artist, ax: MplAxes, data: DataProvider, common: dict) -> None:
    """An image (pixels on a grid) or a colour mesh (cells at given x and y),
    with its colour bar."""
    values = np.asarray(
        data(artist.data if isinstance(artist, ImagePlot) else artist.c)
    )
    scaling = colour_scaling(artist)
    if isinstance(artist, ImagePlot):
        placement = {"origin": artist.origin, "aspect": artist.aspect}
        if artist.extent is not None:
            placement["extent"] = artist.extent
        mappable = ax.imshow(values, cmap=artist.cmap, **scaling, **placement, **common)
    else:
        grid = []
        if artist.x is not None and artist.y is not None:
            grid = [data(artist.x), data(artist.y)]
        mappable = ax.pcolormesh(
            *grid, values, cmap=artist.cmap, shading="auto", **scaling, **common
        )
    bar = artist.colorbar
    if bar is not None and bar.visible:
        label = {"label": bar.label} if bar.label is not None else {}
        ax.figure.colorbar(mappable, ax=ax, **label).ax.set_gid(artist.id)


def colour_scaling(artist) -> dict:
    """How values map to colours: vmin and vmax, or a LogNorm with them."""
    if artist.norm == "log":
        return {"norm": LogNorm(vmin=artist.vmin, vmax=artist.vmax)}
    return {
        key: value
        for key, value in (("vmin", artist.vmin), ("vmax", artist.vmax))
        if value is not None
    }


CURVE_POINTS = 400
"""Points along a fitted curve: smooth at any print size."""


def _draw_fit(
    fit: FitCurve,
    ax: MplAxes,
    data: DataProvider,
    artists: Mapping[str, Artist],
    common: dict,
) -> None:
    """The fitted model across its fit range, where there is data, or across
    all the data; nothing before a fit."""
    from figscribe.fit import evaluate

    target = _referenced(artists, fit.target, FITTABLE, "fit")
    if fit.result is None:
        return
    x = np.asarray(data(target.x), dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return
    low, high = float(x.min()), float(x.max())
    if fit.fit_range is not None and not fit.extend_curve:
        low, high = max(fit.fit_range[0], low), min(fit.fit_range[1], high)
        if not low < high:
            return
    xs = np.linspace(low, high, CURVE_POINTS)
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
    """Data minus fit at every fitted point, with the data's y errors, around
    a dashed zero line."""
    from figscribe.fit import evaluate, in_range, kept

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
    if fit.fit_range is not None or target.left_out:
        used = in_range(x, fit.fit_range) & kept(len(x), target.left_out)
        x, y = x[used], y[used]
        yerr = None if yerr is None else np.asarray(yerr, dtype=float)[used]
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


def _draw_legend(legend: Legend, ax: MplAxes, right: MplAxes | None = None):
    """Draw the legend, with the plots of the right y axis if there is one; it
    carries its axes' id, so a click on it selects them."""
    if legend.position is not None:
        # A dragged legend: anchor its lower-left corner at the axes position.
        placement = {"loc": "lower left", "bbox_to_anchor": legend.position}
    else:
        placement = {"loc": legend.location}
    entries = ()
    if right is not None:
        handles, labels = ax.get_legend_handles_labels()
        more_handles, more_labels = right.get_legend_handles_labels()
        entries = (handles + more_handles, labels + more_labels)
    return ax.legend(
        *entries,
        frameon=legend.frame,
        ncols=legend.ncols,
        fontsize=legend.fontsize,
        **placement,
    )
