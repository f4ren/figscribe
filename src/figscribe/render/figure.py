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
from matplotlib.lines import Line2D
from matplotlib.ticker import (
    AutoMinorLocator,
    FuncFormatter,
    MultipleLocator,
    NullFormatter,
)

from figscribe.convert import convert, plot_data, within
from figscribe.function import evaluator, sets_limits, x_span
from figscribe.io.errors import DataError
from figscribe.model import (
    AllanDeviationPlot,
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
    FunctionPlot,
    Histogram,
    ImagePlot,
    Legend,
    LinePlot,
    ReferenceLine,
    ResidualPlot,
    ScatterPlot,
    ShadedSpan,
)
from figscribe.model.artists import LIKE_THE_PLOT
from figscribe.model.breaks import Breaks, effective_breaks, line_breaks
from figscribe.model.sharing import sharing_group, typed_limits
from figscribe.model.timeaxes import IsTime, as_dates, date_axis, not_on_dates
from figscribe.model.validate import FIT_TARGETS, FITTABLE, unequal_columns
from figscribe.process import not_computable
from figscribe.render.breaks import (
    break_ticks,
    crossings,
    curve_parts,
    cut_out,
    gap_width,
    overlapping,
    pieces,
    squeezed,
)
from figscribe.render.labels import axis_label, panel_label_options, panel_labels
from figscribe.render.layout import (
    creation_order,
    hidden_tick_labels,
    inset_parent,
    share_partner,
    sharing_specs,
)
from figscribe.render.ticks import (
    CommaFormatter,
    CommaLogFormatter,
    MinorLogNumbers,
    comma_formatter,
    date_ticks,
    grid_calls,
    minor_numbers,
    minor_ticks,
    scaling,
    tick_style,
    tick_text,
    ticks_that_fit,
)
from figscribe.times import written_day

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
    figure = _dates_as_written(figure, data)
    cuts = {
        (axes.id, name): line_breaks(figure, i, name)
        for i, axes in enumerate(figure.axes)
        for name in ("x", "y")
    }
    drawn = _render(figure, data, view, cuts)
    applied = {key: drawn.figscribe_breaks.get(key, ([],))[0] for key in cuts}
    if applied == cuts:
        return drawn
    # Which breaks an axis is drawn with can depend on its data, which is only
    # known once they are plotted. Plot again, cutting lines and curves at
    # those and no others, as the script does.
    return _render(figure, data, view, applied)


def _dates_as_written(figure: Figure, data: DataProvider) -> Figure:
    """The figure with every place on a date axis, and every range of dates of
    a plot, as the script writes it."""

    def is_time(ref: ColumnRef) -> bool:
        return np.asarray(data(ref)).dtype.kind == "M"

    panels = []
    changed = False
    for i, axes in enumerate(figure.axes):
        dated = {
            field
            for field in ("x", "y", "y_right")
            if getattr(axes, field) is not None and date_axis(figure, i, field, is_time)
        }
        update: dict = {}
        for field in dated:
            spec = getattr(axes, field)
            places = {}
            if spec.limits is not None:
                places["limits"] = tuple(map(written_day, spec.limits))
            if spec.ticks is not None:
                places["ticks"] = [written_day(t) for t in spec.ticks]
            update[field] = spec.model_copy(update=places)
        artists = [_artist_as_written(a, axes, dated, is_time) for a in axes.artists]
        if any(a is not b for a, b in zip(artists, axes.artists, strict=True)):
            update["artists"] = artists
        changed = changed or bool(update)
        panels.append(axes.model_copy(update=update) if update else axes)
    return figure.model_copy(update={"axes": panels}) if changed else figure


def _artist_as_written(artist, axes: Axes, dated: set[str], is_time: IsTime):
    """`artist` with its places on the date axes `dated` of `axes`, and its own
    range of dates, as the script writes them; itself if it has none."""
    if isinstance(artist, FITTABLE):
        if artist.x_range is None or not as_dates(artist, "x", is_time):
            return artist
        ends = tuple(map(written_day, artist.x_range))
        return artist.model_copy(update={"x_range": ends})
    right = artist.axis == "right" and axes.y_right is not None
    x, y = "x" in dated, ("y_right" if right else "y") in dated
    places: dict = {}
    if isinstance(artist, ReferenceLine | ShadedSpan):
        if x if artist.orientation == "vertical" else y:
            names = ("at",) if isinstance(artist, ReferenceLine) else ("start", "end")
            places = {n: written_day(getattr(artist, n)) for n in names}
    elif isinstance(artist, Annotation) and artist.coords == "data" and (x or y):
        for name in ("position", "arrow_to"):
            point = getattr(artist, name)
            if point is not None:
                places[name] = tuple(
                    written_day(v) if on else v
                    for v, on in zip(point, (x, y), strict=True)
                )
    return artist.model_copy(update=places) if places else artist


def _render(
    figure: Figure,
    data: DataProvider,
    view: View | None,
    cuts: Mapping[tuple[str, str], Breaks],
) -> MplFigure:
    """`render`, with the breaks to cut the lines of each panel at."""
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

        def is_time(ref: ColumnRef) -> bool:
            return np.asarray(data(ref)).dtype.kind == "M"

        dated = {
            (i, field)
            for i, axes in enumerate(figure.axes)
            for field in ("x", "y", "y_right")
            if getattr(axes, field) is not None and date_axis(figure, i, field, is_time)
        }
        skipped = {
            a.id
            for i, axes in enumerate(figure.axes)
            for a in axes.artists
            if not_on_dates(figure, i, a, is_time)
        } | set(not_computable(figure, data))
        # Where each function is drawn and whether it scales its axis: from the
        # model and the data, never from what is on the axes so far.
        places = {
            a.id: (x_span(figure, i, a, data), sets_limits(figure, i, a))
            for i, axes in enumerate(figure.axes)
            for a in axes.artists
            if isinstance(a, FunctionPlot) and a.id not in skipped
        }
        axs: dict[int, MplAxes] = {}
        ticked: list[tuple[MplAxes, str, AxisSpec]] = []
        # By (gid, "x" or "y"): the other panels' settings for the same axis.
        shared: dict[tuple[str, str], list[AxisSpec]] = {}
        twins: dict[int, MplAxes] = {}
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
            drawn = _draw_axes(
                axes,
                ax,
                data,
                figure.unit_format,
                artists,
                figure.open_frame,
                figure.decimal_comma,
                tuple(cuts[axes.id, name] for name in ("x", "y")),
                typed_limits(figure, i, "x"),
                places,
                {field for j, field in dated if j == i},
                skipped,
            )
            if len(drawn) > 2:
                twins[i] = drawn[2][0]
            for part, name, _ in drawn:
                field = "y_right" if part.get_gid().endswith(RIGHT) else name
                shared[part.get_gid(), name] = sharing_specs(figure, i, field)
            ticked += drawn
            axs[i] = ax

        broken = _break_scales(figure, axs, twins, dated)
        # The gids and sides of the date axes.
        date_sides = {
            (figure.axes[i].id + (RIGHT if field == "y_right" else ""), field[0])
            for i, field in dated
        }

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
        # The ticks of broken axes, for the script, which writes them out.
        broken_ticks: dict[tuple[str, str], tuple] = {}
        for ax, name, spec in ticked:
            interval = ax.get_xlim() if name == "x" else ax.get_ylim()
            key = ax.get_gid(), name
            if key in broken:
                low, high = sorted(interval)
                breaks, width, _ = broken[key]
                visible = sum(b - a for a, b in pieces(breaks, low, high))
                fitting = ticks_that_fit(spec, (low, low + visible))
                broken_ticks[key] = _set_break_ticks(ax, name, fitting, breaks, width)
            else:
                fitting = ticks_that_fit(spec, interval)
            others = shared[key]
            comma = figure.decimal_comma
            if key in date_sides:
                _apply_date_ticks(ax, name, fitting)
            else:
                _apply_ticks(ax, name, fitting, comma, others, key in broken)
            if rounded:
                ax.autoscale_view(scalex=name == "x", scaley=name == "y")

        for i, (hide_x, hide_y) in enumerate(hidden_tick_labels(figure)):
            ax = axs[i]
            if hide_x:
                ax.xaxis.set_tick_params(which="both", labelbottom=False)
            if hide_y:
                ax.yaxis.set_tick_params(which="both", labelleft=False)

        # No gid: a panel label is not a note to drag.
        for i, text in panel_labels(figure).items():
            axs[i].annotate(text, **panel_label_options(figure.panel_labels))

        aligned = aligned_axes(figure)
        if figure.align_labels and aligned:
            fig.align_labels(
                [ax for i in aligned for ax in (axs[i], twins.get(i)) if ax is not None]
            )

        # Last, when everything to be clipped is there.
        for i, axes in enumerate(figure.axes):
            x_breaks, y_breaks = (
                broken.get((axes.id, n), ([],))[0] for n in ("x", "y")
            )
            if x_breaks or y_breaks:
                frame = not figure.open_frame
                cut_out(axs[i], x_breaks, y_breaks, twins.get(i), frame)
    fig.figscribe_breaks = broken
    fig.figscribe_break_ticks = broken_ticks
    return fig


def _break_scales(
    figure: Figure,
    axs: dict[int, MplAxes],
    twins: dict[int, MplAxes],
    dated: set[tuple[int, str]],
) -> dict[tuple[str, str], tuple]:
    """Give each broken axis its scale; returns (breaks drawn, width of their
    gaps, range if it was automatic) by (gid, "x" or "y"). Panels sharing an
    axis have one scale between them.

    The gap's width follows from the range the model gives, or that the data
    fill, so that zooming the preview does not change it.
    """
    broken: dict[tuple[str, str], tuple] = {}
    for i in range(len(figure.axes)):
        for name in ("x", "y"):
            group = sharing_group(figure, i, name)
            if i != group[0] or not (breaks := effective_breaks(figure, i, name)):
                continue
            if (i, name) in dated:
                continue  # no breaks on a date axis
            first = axs[i]
            given = any(getattr(figure.axes[j], name).limits for j in group)
            if given:
                ends = list(first.get_xlim() if name == "x" else first.get_ylim())
            else:
                drawn = [axs[j] for j in group]
                if name == "x":
                    drawn += [twins[j] for j in group if j in twins]
                ends = [
                    end
                    for ax in drawn
                    for end in getattr(ax.dataLim, f"interval{name}")
                    if np.isfinite(end)
                ]
            if not ends:
                continue
            low, high = float(min(ends)), float(max(ends))
            applied = overlapping(breaks, low, high)
            if not applied or not (width := gap_width(applied, low, high)) > 0:
                continue
            set_scale = first.set_xscale if name == "x" else first.set_yscale
            set_scale("function", functions=squeezed(applied, width))
            fixed = None
            if not given:
                # An automatic range is worked out for the squeezed scale (a
                # reference line may have settled the linear one already) and
                # fixed, rounded, so that the script can write it and draws
                # with the very same numbers.
                first.autoscale_view(scalex=name == "x", scaley=name == "y")
                ends = first.get_xlim() if name == "x" else first.get_ylim()
                fixed = tuple(float(f"{end:.6g}") for end in ends)
                (first.set_xlim if name == "x" else first.set_ylim)(*fixed)
            for j in group:
                broken[figure.axes[j].id, name] = applied, width, fixed
    return broken


def _set_break_ticks(
    ax: MplAxes, name: str, spec: AxisSpec, breaks: Breaks, width: float
) -> tuple:
    """Place the ticks of a broken axis, each one itself: Matplotlib would put
    them into the gaps. Returns (major, typed labels, minor)."""
    axis = ax.xaxis if name == "x" else ax.yaxis
    low, high = ax.get_xlim() if name == "x" else ax.get_ylim()
    major, labels, minor = break_ticks(
        breaks,
        low,
        high,
        axis.get_tick_space(),
        ticks=spec.ticks,
        labels=spec.tick_labels,
        step=spec.major_step,
        parts=spec.minor_divisions,
        minor=spec.minor_ticks,
        clear=width,
    )
    axis.set_ticks(major, labels=labels)
    if minor:
        axis.set_ticks(minor, minor=True)
    else:
        axis.minorticks_off()
    return major, labels, minor


def aligned_axes(figure: Figure) -> list[int]:
    """The panels whose labels are lined up: those in the grid, not insets,
    and only when there are two or more; one panel has nothing to line up
    with. Their right y axes go with them.

    Without the constrained layout a panel with a colour bar is left out too:
    Matplotlib then splits its grid cell for the bar, which counts the rows
    and columns from zero again, and the alignment would take the panel for
    one in the first row or column."""
    grid = [
        i
        for i, axes in enumerate(figure.axes)
        if axes.inset is None
        and (figure.layout.constrained_layout or not _has_colour_bar(axes))
    ]
    return grid if len(grid) > 1 else []


def _has_colour_bar(axes: Axes) -> bool:
    """Whether the panel draws a colour bar."""
    return any(
        getattr(artist, "colorbar", None) is not None and artist.colorbar.visible
        for artist in axes.artists
    )


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
    open_frame: bool = False,
    comma: bool = False,
    breaks: tuple[Breaks, Breaks] = ([], []),
    x_limits: tuple[float, float] | None = None,
    places: Mapping[str, tuple] | None = None,
    dated: set[str] = frozenset(),
    skipped: set[str] = frozenset(),
) -> list[tuple[MplAxes, str, AxisSpec]]:
    """Draw one panel; returns its axes whose ticks are still to be placed."""
    if axes.title is not None:
        size = {"fontsize": axes.title_size} if axes.title_size else {}
        ax.set_title(axes.title, **size)
    _apply_axis(ax, "x", axes.x, unit_format, "x" in dated)
    _apply_axis(ax, "y", axes.y, unit_format, "y" in dated)
    right = None
    if axes.y_right is not None:
        right = ax.twinx()
        right.set_gid(f"{axes.id}{RIGHT}")
        if open_frame:
            right.spines["right"].set_visible(True)  # the frame left it out
        _apply_axis(right, "y", axes.y_right, unit_format, "y_right" in dated)
    for style in grid_calls(axes):
        if style.get("linewidth", 0) is None:  # half the style's
            style["linewidth"] = matplotlib.rcParams["grid.linewidth"] / 2
        ax.grid(True, axis=axes.grid_axis, **style)

    for artist in axes.artists:
        if artist.id in skipped:
            continue  # the list of problems says why
        # Without a right axis, a plot meant for it is drawn against the left
        # one; validate_references reports it.
        target = right if artist.axis == "right" and right is not None else ax
        # The breaks of the y axis are the left one's.
        cut = breaks if target is ax else (breaks[0], [])
        place = (places or {}).get(artist.id)
        _draw_artist(artist, target, data, artists, comma, cut, x_limits, place)

    if axes.legend.visible:
        _draw_legend(axes.legend, ax, right).set_gid(axes.id)

    ticked = [(ax, "x", axes.x), (ax, "y", axes.y)]
    if axes.y_right is not None:
        ticked.append((right, "y", axes.y_right))
    return ticked


def _apply_axis(
    ax: MplAxes, name: str, spec: AxisSpec, unit_format: str, dates: bool = False
) -> None:
    axis = ax.xaxis if name == "x" else ax.yaxis
    label = axis_label(spec, unit_format)
    if label is not None:
        size = {"fontsize": spec.label_size} if spec.label_size else {}
        axis.set_label_text(label, **size)
    if spec.labelpad is not None:
        axis.labelpad = spec.labelpad

    set_scale, set_lim = (
        (ax.set_xscale, ax.set_xlim) if name == "x" else (ax.set_yscale, ax.set_ylim)
    )
    # A new axis is linear, and the script says nothing then either. Setting
    # "linear" on a shared axis would reset the ticks a panel sharing it has set.
    if dates:
        # Numbers are then days since 1970; a date axis has no other scale.
        (ax.xaxis_date if name == "x" else ax.yaxis_date)()
    elif spec.scale == "symlog" and spec.symlog_linthresh is not None:
        set_scale("symlog", linthresh=spec.symlog_linthresh)
    elif spec.scale != "linear":
        set_scale(spec.scale)

    if spec.limits is not None:
        set_lim(*spec.limits)
    if spec.inverted:
        # Not a toggle: panels that share an axis each ask for it.
        axis.set_inverted(True)
    if spec.ticks is not None:
        axis.set_ticks(spec.ticks, labels=spec.tick_labels)


def _locate_ticks(axis, spec: AxisSpec) -> None:
    """Where the major and minor ticks of an axis go."""
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


def _apply_ticks(
    ax: MplAxes,
    name: str,
    spec: AxisSpec,
    comma: bool,
    shared: list[AxisSpec],
    broken: bool = False,
) -> None:
    """The tick step, minor ticks and tick numbers, once the range is known; on
    a broken axis the ticks are placed already, and only their numbers are
    left."""
    axis = ax.xaxis if name == "x" else ax.yaxis
    if not broken:
        _locate_ticks(axis, spec)
    how, _ = minor_ticks(spec)
    if scaling(spec) is not None:
        axis.set_major_formatter(
            FuncFormatter(lambda value, _: tick_text(value, spec, comma))
        )
    elif kind := comma_formatter(spec, comma, shared):
        _comma_numbers(axis, kind, minor=spec.scale == "log" and how != "off")
    minor = minor_numbers(spec)
    if minor == "silent":
        axis.set_minor_formatter(NullFormatter())
    elif minor == "ours":
        axis.set_minor_formatter(MinorLogNumbers(axis.get_major_formatter()))
    if spec.tick_size is not None:
        ax.tick_params(axis=name, which="both", labelsize=spec.tick_size)


def _apply_date_ticks(ax: MplAxes, name: str, spec: AxisSpec) -> None:
    """The ticks of a date axis: its own numbers; a tick step, a number format
    and a factor are for numbers."""
    axis = ax.xaxis if name == "x" else ax.yaxis
    if spec.tick_size is not None:  # first: it decides how many labels fit
        ax.tick_params(axis=name, which="both", labelsize=spec.tick_size)
    date_ticks(axis, spec)
    how, value = minor_ticks(spec)
    if how == "parts":
        axis.set_minor_locator(AutoMinorLocator(value))
    elif how == "on":
        axis.set_minor_locator(AutoMinorLocator())
    else:
        axis.minorticks_off()


def _comma_numbers(axis, kind: str, minor: bool) -> None:
    """Matplotlib's own numbers of `axis`, with a decimal comma; `kind` as
    comma_formatter gives it. `minor` for a log axis, which labels minor ticks
    too when it spans less than a decade."""
    if kind == "linear":
        axis.set_major_formatter(CommaFormatter())
        return
    axis.set_major_formatter(CommaLogFormatter())
    if minor:
        axis.set_minor_formatter(CommaLogFormatter())


def _draw_artist(
    artist: Artist,
    ax: MplAxes,
    data: DataProvider,
    artists: Mapping[str, Artist],
    comma: bool = False,
    cut: tuple[Breaks, Breaks] = ([], []),
    x_limits: tuple[float, float] | None = None,
    place: tuple | None = None,
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
        _draw_points(artist, ax, data, common, artists, cut)
    elif isinstance(artist, Histogram):
        values = convert(data(artist.values), artist.x_conversion)
        # np.histogram cannot place NaN or inf; they are left out, like in a fit.
        values = values[np.isfinite(values) & within(values, artist.x_range)]
        spans = artist.x_range is not None and isinstance(artist.bins, int)
        _, _, patches = ax.hist(
            values,
            bins=artist.bins,
            density=artist.density,
            histtype=artist.histtype,
            color=artist.color,
            **({"range": artist.x_range} if spans else {}),
            **common,
        )
        for patch in patches:
            patch.set_gid(artist.id)
    elif isinstance(artist, Annotation):
        _draw_annotation(artist, ax, common)
    elif isinstance(artist, ReferenceLine):
        draw = ax.axvline if artist.orientation == "vertical" else ax.axhline
        draw(
            artist.at,
            color=artist.color,
            linestyle=artist.linestyle,
            linewidth=artist.linewidth,
            **common,
        )
    elif isinstance(artist, ShadedSpan):
        draw = ax.axvspan if artist.orientation == "vertical" else ax.axhspan
        # No edge: in the band's own color it would draw a darker outline.
        draw(artist.start, artist.end, color=artist.color, linewidth=0, **common)
    elif isinstance(artist, ImagePlot | ColorMesh):
        _draw_2d(artist, ax, data, common, comma)
    elif isinstance(artist, AllanDeviationPlot):
        _draw_allan(artist, ax, data, common, cut)
    elif isinstance(artist, FunctionPlot):
        _draw_function(artist, ax, common, cut, *place)
    elif isinstance(artist, FitCurve):
        _draw_fit(artist, ax, data, artists, common, cut, x_limits)
    elif isinstance(artist, ResidualPlot):
        _draw_residuals(artist, ax, data, artists, common, cut)
    else:
        raise NotImplementedError(
            f"rendering {artist.kind!r} artists is not implemented yet"
        )


LEFT_OUT_COLOR = "0.7"
"""Light grey: left-out points stay visible, but stand back."""


def _draw_points(
    artist,
    ax: MplAxes,
    data: DataProvider,
    common: dict,
    artists: Mapping,
    cut: tuple[Breaks, Breaks],
) -> None:
    """A line, scatter or error bar plot. With rows left out: the kept rows as
    styled, the line broken at the left-out ones; the line running on through
    them in their color; then their markers and error bars, without a legend
    entry. Each part that shows points carries `rows`, its data rows, for
    clicks."""
    from figscribe.fit import FitError, kept

    try:
        converted = plot_data(artist, data)
    except FitError as exc:  # a reduction counts the rows left out
        raise DataError(f"{artist.label or artist.kind}: {exc}") from None
    columns = {
        name: values
        for name in ("x", "y", "xerr", "yerr")
        if (values := getattr(converted, name)) is not None
        and (name in ("x", "y") or hasattr(artist, name))  # a line has no errors
    }
    # Errors drawn as a band are not drawn as bars, of the left-out rows neither.
    spread = columns.pop("yerr", None) if banded(artist) else None
    count = len(columns["x"])
    used = converted.used
    if converted.reduced:  # the rows left out and outside the range are gone
        shown = np.ones(count, dtype=bool)
    else:
        try:
            shown = kept(count, artist.left_out)
        except FitError as exc:
            raise DataError(f"{artist.label or artist.kind}: {exc}") from None
        # Rows outside the plot's range are not drawn at all, not even apart.
        shown &= _inside_fits(artist, artists, columns["x"]) & used
    y = columns["y"]
    if not shown.all():
        columns["y"] = np.where(shown, y, np.nan)
    # Where a line or band would cross a break; none is drawn there.
    at = crossings(columns["x"], y, *cut)
    rows = np.arange(count) if converted.rows is None else converted.rows
    drawn = columns
    if at.size and getattr(artist, "linestyle", "none") not in NO_LINE:
        drawn = {name: _apart(values, at) for name, values in columns.items()}
        rows = np.insert(rows, at, -1)
    part = _draw_part(artist, ax, drawn, {}, common)
    part.rows = rows
    if spread is not None:
        x, mid, half, kept_rows = columns["x"], y, spread, shown
        where = None if shown.all() else shown
        if at.size:
            x, mid, half = (_apart(v, at) for v in (x, mid, half))
            where = None if where is None else np.insert(kept_rows, at, False)
        _draw_band(artist, ax, x, mid, half, where, part.get_color())
    if shown.all():
        return
    color = artist.left_out_color or LEFT_OUT_COLOR
    apart = {**common, "label": "_nolegend_"}
    linestyle = like_the_plot(artist, "linestyle")
    if linestyle not in NO_LINE:
        x = columns["x"]
        touching = ~(shown[:-1] & shown[1:]) & used[:-1] & used[1:]
        touching[at - 1] = False
        width = {"linewidth": artist.linewidth} if hasattr(artist, "linewidth") else {}
        ax.plot(
            _segments(x)[touching].ravel(),
            _segments(y)[touching].ravel(),
            color=color,
            linestyle=linestyle,
            **width,
            **apart,
        )
    marker = like_the_plot(artist, "marker")
    if marker is None and not isinstance(artist, ErrorbarPlot):
        return  # nothing to show of the points themselves
    out = ~shown & used
    values = {name: column[out] for name, column in columns.items()}
    values["y"] = y[out]
    style = {"color": color, "marker": marker or "none", "linestyle": "none"}
    _draw_part(artist, ax, values, style, apart).rows = np.flatnonzero(out)


def _apart(values: np.ndarray, at: np.ndarray) -> np.ndarray:
    """The values with a NaN before each position of `at`."""
    return np.insert(np.asarray(values, dtype=float), at, np.nan)


def banded(artist) -> bool:
    """Whether the plot draws its y errors as a band."""
    return getattr(artist, "band", None) is not None and artist.yerr is not None


BAND_BEHIND = 0.1
"""How far below its plot a band is drawn, so that the line stays on top."""


def band_options(artist) -> dict[str, float]:
    """The band's opacity and drawing order, rounded so that the script shows
    0.2 rather than 0.20000000000000004."""
    return {
        "alpha": round(artist.band.alpha * artist.alpha, 6),
        "zorder": round(artist.zorder - BAND_BEHIND, 6),
    }


def _draw_band(artist, ax: MplAxes, x, y, spread, where, color) -> None:
    """The band of y ± spread, in the plot's color unless it has its own, with
    a gap at the rows not shown."""
    ax.fill_between(
        x,
        y - spread,
        y + spread,
        where=where,
        color=artist.band.color or color,
        linewidth=0,
        visible=artist.visible,
        label="_nolegend_",
        gid=artist.id,
        **band_options(artist),
    )


def _inside_fits(artist, artists: Mapping, x: np.ndarray) -> np.ndarray:
    """Which points lie inside the range of every fit of the plot that draws
    the points outside like left-out ones."""
    from figscribe.fit import in_range

    inside = np.ones(x.shape, dtype=bool)
    for fit in artists.values():
        if (
            isinstance(fit, FitCurve)
            and fit.target == artist.id
            and fit.outside_as_left_out
            and fit.fit_range is not None
            and fit.drawn_result() is not None
        ):
            inside &= in_range(x, fit.fit_range)
    return inside


NO_LINE = (None, "none", "None", "", " ")
"""Line styles that draw no line."""


def like_the_plot(artist, name: str):
    """The left-out points' `name` ("marker", "linestyle"): the plot's own
    when set to "same"."""
    value = getattr(artist, f"left_out_{name}", "none")
    return getattr(artist, name, None) if value == LIKE_THE_PLOT else value


def _segments(values: np.ndarray) -> np.ndarray:
    """Each step from one row to the next as (from, to, NaN), one per row."""
    gap = np.full(values.size - 1, np.nan)
    return np.column_stack([values[:-1], values[1:], gap])


def _draw_part(artist, ax: MplAxes, values: dict, style: dict, options: dict):
    """Draw `values` as the plot does, with `style` over its own; return the
    Matplotlib artist that shows the points."""
    if isinstance(artist, LinePlot) or (banded(artist) and "xerr" not in values):
        return ax.plot(
            values["x"],
            values["y"],
            color=style.get("color", artist.color),
            linestyle=style.get("linestyle", artist.linestyle),
            linewidth=artist.linewidth,
            marker=style.get("marker", artist.marker),
            markersize=artist.markersize,
            **options,
        )[0]
    if isinstance(artist, ScatterPlot):
        return ax.scatter(
            values["x"],
            values["y"],
            s=artist.size,
            color=style.get("color", artist.color),
            marker=style.get("marker", artist.marker),
            edgecolors=artist.edgecolor,
            **options,
        )
    container = ax.errorbar(
        values["x"],
        values["y"],
        xerr=values.get("xerr"),
        yerr=values.get("yerr"),
        color=style.get("color", artist.color),
        linestyle=style.get("linestyle", artist.linestyle),
        linewidth=artist.linewidth,
        marker=style.get("marker", artist.marker),
        markersize=artist.markersize,
        capsize=artist.capsize,
        elinewidth=artist.elinewidth,
        **options,
    )
    # A container has no gid of its own; tag every part so a click on a cap or
    # a bar maps back to the artist as well.
    for part in container.get_children():
        part.set_gid(artist.id)
    return container.lines[0]


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
    if note.background is not None:
        style["bbox"] = {
            "boxstyle": "round,pad=0.2",
            "facecolor": note.background,
            "edgecolor": "none",
        }
    ax.annotate(
        note.text,
        xy=note.arrow_to if note.arrow_to is not None else note.position,
        xycoords=coords,
        **arrow,
        **style,
        **common,
    )


def _draw_2d(
    artist, ax: MplAxes, data: DataProvider, common: dict, comma: bool
) -> None:
    """An image (pixels on a grid) or a colour mesh (cells at given x and y),
    with its colour bar."""
    values = np.asarray(
        data(artist.data if isinstance(artist, ImagePlot) else artist.c)
    )
    if values.ndim != 2:
        what = "an image" if isinstance(artist, ImagePlot) else "a color mesh"
        raise DataError(
            f"{artist.label or what} needs 2-D data, a table of values, but the "
            f"data chosen is {values.ndim}-D"
        )
    scaling = colour_scaling(artist)
    if isinstance(artist, ImagePlot):
        placement = {"origin": artist.origin, "aspect": artist.aspect}
        if artist.extent is not None:
            placement["extent"] = artist.extent
        mappable = ax.imshow(values, cmap=artist.cmap, **scaling, **placement, **common)
    else:
        grid = []
        if artist.x is not None or artist.y is not None:
            # Without one of them, the cells are numbered along it.
            rows, cols = values.shape
            x = data(artist.x) if artist.x is not None else np.arange(cols)
            y = data(artist.y) if artist.y is not None else np.arange(rows)
            for name, positions, count in (("x", x, cols), ("y", y, rows)):
                if len(positions) not in (count, count + 1):
                    raise DataError(
                        f"{artist.label or 'the color mesh'} has {count} cells "
                        f"along {name}, but {len(positions)} {name} positions; it "
                        f"needs {count} (the cells' centres) or {count + 1} (their "
                        "edges)"
                    )
            grid = [x, y]
        mappable = ax.pcolormesh(
            *grid, values, cmap=artist.cmap, shading="auto", **scaling, **common
        )
    bar = artist.colorbar
    if bar is not None and bar.visible:
        label = {"label": bar.label} if bar.label is not None else {}
        colorbar = ax.figure.colorbar(mappable, ax=ax, **label)
        colorbar.ax.set_gid(artist.id)
        if comma:
            kind = "log" if artist.norm == "log" else "linear"
            _comma_numbers(colorbar.ax.yaxis, kind, minor=True)


def _draw_allan(
    artist: AllanDeviationPlot,
    ax: MplAxes,
    data,
    common: dict,
    cut: tuple[Breaks, Breaks],
) -> None:
    """σ_y(τ) against τ, computed as the script computes it (figscribe.allan).

    A series with gaps is not drawn; validate_references says why.
    """
    from figscribe.allan import allan_points

    try:
        points = allan_points(artist, data)
    except DataError as exc:
        raise DataError(f"{artist.label or 'the Allan deviation'}: {exc}") from None
    if points is None:
        return
    tau, adev, yerr = points
    at = crossings(tau, adev, *cut)
    if at.size and artist.linestyle not in NO_LINE:
        tau, adev = _apart(tau, at), _apart(adev, at)
        yerr = None if yerr is None else _apart(yerr, at)
    container = ax.errorbar(
        tau,
        adev,
        yerr=yerr,
        color=artist.color,
        marker=artist.marker or "none",
        markersize=artist.markersize,
        linestyle=artist.linestyle,
        linewidth=artist.linewidth,
        **common,
    )
    for part in container.get_children():
        part.set_gid(artist.id)


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


def _samples(low: float, high: float, breaks: Breaks, log: bool):
    """Where a curve from `low` to `high` is worked out: evenly, on each stretch
    of a broken x axis so that a short one stays smooth; None if breaks leave
    nothing of it."""
    if overlapping(breaks, low, high):
        parts = curve_parts(low, high, breaks, CURVE_POINTS)
        if not parts:
            return None
        return np.concatenate([np.linspace(*part) for part in parts])
    return (np.geomspace if log else np.linspace)(low, high, CURVE_POINTS)


def _draw_function(
    function: FunctionPlot,
    ax: MplAxes,
    common: dict,
    cut: tuple[Breaks, Breaks],
    span: tuple[float, float] | None,
    sets: str,
) -> None:
    """The formula over `span`; nothing where it cannot be read or there is no
    range. `sets` says which limits it sets, as `function.sets_limits`."""
    f = evaluator(function)
    if f is None or span is None:
        return
    low, high = span
    xs = _samples(low, high, cut[0], ax.get_xscale() == "log" and low > 0)
    if xs is None:
        return
    ys = f(xs)
    at = crossings(xs, ys, *cut)
    if at.size:
        xs, ys = _apart(xs, at), _apart(ys, at)
    style = {
        "color": function.color,
        "linestyle": function.linestyle,
        "linewidth": function.linewidth,
    }
    if sets == "both":
        ax.plot(xs, ys, **style, **common)
        return
    # Added as it is: Matplotlib then leaves the limits to the data.
    ax.add_artist(Line2D(xs, ys, transform=ax.transData, **style, **common))
    if sets != "none":  # but nothing else scales this one axis
        x = sets == "x"
        ax.update_datalim(np.column_stack([xs, ys]), updatex=x, updatey=not x)
        ax.autoscale_view(scalex=x, scaley=not x)


def _draw_fit(
    fit: FitCurve,
    ax: MplAxes,
    data: DataProvider,
    artists: Mapping[str, Artist],
    common: dict,
    cut: tuple[Breaks, Breaks],
    x_limits: tuple[float, float] | None,
) -> None:
    """The fitted model across the ends given to it, else across its fit range,
    where there is data, or across all the data; nothing before a fit."""
    from figscribe.fit import evaluate, fitted_points

    target = _referenced(artists, fit.target, FIT_TARGETS, "fit")
    if fit.drawn_result() is None:
        return
    shown = plot_data(target, data)
    if not fitted_points(shown, getattr(target, "left_out", ()), fit.fit_range).any():
        return  # the fit has no point to run on, and the script no fit
    x = shown.x[np.isfinite(shown.x) & shown.used]
    if x.size == 0:
        return
    first, last = float(x.min()), float(x.max())  # where the data begin and end
    ends = fit.curve_ends(first, last, x_limits)
    if ends is None:
        return
    low, high = ends
    look = fit.extrapolated_look(ends, (first, last))
    # Evenly in log x for an Allan deviation, and over ends of the user's, which
    # may reach across decades.
    log = (
        ax.get_xscale() == "log"
        and low > 0
        and (
            isinstance(target, AllanDeviationPlot)
            or fit.given_ends(x_limits) is not None
        )
    )
    xs = _samples(low, high, cut[0], log)
    if xs is None:
        return
    if look:  # both parts reach the data's ends, so there is no gap
        xs = np.union1d(xs, np.clip([first, last], low, high))
    ys = evaluate(fit.model, fit.result.parameters, xs)
    at = crossings(xs, ys, *cut)
    if at.size:
        xs, ys = _apart(xs, at), _apart(ys, at)
    measured = ys
    if look:
        measured = np.where((xs >= first) & (xs <= last), ys, np.nan)
    (line,) = ax.plot(
        xs,
        measured,
        color=fit.color,
        linestyle=fit.linestyle,
        linewidth=fit.linewidth,
        **common,
    )
    if look:
        ax.plot(
            xs,
            np.where((xs <= first) | (xs >= last), ys, np.nan),
            **look | {"color": look["color"] or line.get_color()},
            **common | {"label": "_nolegend_"},
        )


def _draw_residuals(
    residuals: ResidualPlot,
    ax: MplAxes,
    data: DataProvider,
    artists: Mapping[str, Artist],
    common: dict,
    cut: tuple[Breaks, Breaks],
) -> None:
    """Data minus fit at every fitted point, with the data's y errors, around
    a dashed zero line."""
    from figscribe.fit import evaluate, fitted_points

    fit = _referenced(artists, residuals.target, (FitCurve,), "residual plot")
    target = _referenced(artists, fit.target, FIT_TARGETS, "fit")
    if residuals.zero_line:
        ax.axhline(
            0.0,
            color=residuals.zero_color,
            linewidth=residuals.zero_linewidth,
            linestyle=residuals.zero_linestyle,
            zorder=1,
        )
    if fit.drawn_result() is None:
        return
    shown = plot_data(target, data)
    x, y, yerr = shown.x, shown.y, shown.yerr
    used = fitted_points(shown, getattr(target, "left_out", ()), fit.fit_range)
    if not used.any():
        return  # no point is fitted; the script draws nothing either
    if not used.all():
        x, y = x[used], y[used]
        yerr = None if yerr is None else yerr[used]
    left = y - evaluate(fit.model, fit.result.parameters, x)
    at = crossings(x, left, *cut)
    if at.size and residuals.linestyle not in NO_LINE:
        x, left = _apart(x, at), _apart(left, at)
        yerr = None if yerr is None else _apart(yerr, at)
    container = ax.errorbar(
        x,
        left,
        yerr=yerr,
        color=residuals.color,
        marker=residuals.marker,
        markersize=residuals.markersize,
        linestyle=residuals.linestyle,
        linewidth=residuals.linewidth,
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
