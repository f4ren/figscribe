"""Changing a plot's units or range as one undoable step (decision 0041).

Everything typed in a plot's shown units is converted along, so that the
same rows stay selected and the same places marked: its range, its fits'
ranges, and on its axis the limits, ticks, step, breaks and the reference lines,
shaded ranges and notes, unless another data plot is drawn against that
axis in the same panel. Panels sharing the axis follow if they show no other
data against it, as do the axes of its fits' residuals, in y without the
offset. The plot's fits are run again on the converted data, in the same step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np

from figscribe.commands import Command, CommandError, Macro, SetField, find
from figscribe.convert import convert, linear, plot_data, start
from figscribe.fit import FitError, refit_in_edit
from figscribe.io.errors import DataError
from figscribe.model import (
    AllanDeviationPlot,
    Annotation,
    Axes,
    AxisSpec,
    ColorMesh,
    ColumnRef,
    Conversion,
    ErrorbarPlot,
    FitCurve,
    FunctionPlot,
    Histogram,
    ImagePlot,
    LinePlot,
    Project,
    ReferenceLine,
    ResidualPlot,
    ScatterPlot,
    ShadedSpan,
    Smoothing,
)
from figscribe.model.sharing import sharing_group
from figscribe.model.timeaxes import date_axis, time_columns_of
from figscribe.process import measured, processes
from figscribe.times import date_text

DataProvider = Callable[[ColumnRef], np.ndarray]

DATA_PLOTS = (
    LinePlot,
    ScatterPlot,
    ErrorbarPlot,
    Histogram,
    AllanDeviationPlot,
    ImagePlot,
    ColorMesh,
)
"""Plots whose data an axis shows; while another of them is drawn against
the axis, the axis keeps its numbers."""

CONVERTIBLE = (LinePlot, ScatterPlot, ErrorbarPlot, Histogram, AllanDeviationPlot)


def set_conversion(
    project: Project,
    plot_id: str,
    axis: Literal["x", "y"],
    conversion: Conversion | None,
    data: DataProvider,
) -> Macro:
    """Show the plot's `axis` values with `conversion` (None: as in the
    file). A FitError, changing nothing, if a predefined model that was drawn
    can then not be run. A fit that does not converge, and an own formula that
    cannot be fitted, is left not fitted instead."""
    plot = _plot(project, plot_id)
    field = f"{axis}_conversion"
    if field not in type(plot).model_fields:
        raise FitError(f"a {plot.kind} plot has no {axis} to convert")
    old = getattr(plot, field)
    remap, rescale = _mapping(plot, axis, old, conversion, data)

    # Back to dates there is nothing to fit: the fits are left not fitted.
    to_dates = conversion is None and _holds_times(plot, axis, data)
    steps: list[Command] = [SetField(plot_id, (field,), conversion)]
    if axis == "x" and plot.x_range is not None:
        steps.append(SetField(plot_id, ("x_range",), _ends(plot.x_range, remap)))
    for fit in _fits_of(project, plot_id):
        if axis == "x" and fit.fit_range is not None:
            steps.append(SetField(fit.id, ("fit_range",), _ends(fit.fit_range, remap)))
        if axis == "x" and fit.curve_range is not None:
            ends = _ends(fit.curve_range, remap)
            steps.append(SetField(fit.id, ("curve_range",), ends))
    steps += _start_values_afresh(project, plot_id)
    keeps = _kept_for_dates(project, plot, axis, old, conversion, data)
    if axis == "y" and getattr(plot, "normalize", None) is not None:
        # Normalised values and their axis do not change with the unit.
        keeps = _always
    steps += _axis_follows(project, plot, axis, old, conversion, remap, rescale, keeps)
    # An own formula keeps start values in the old units; where it cannot be
    # fitted from them it is left not fitted rather than keep the units.
    own = {f.id for f in _fits_of(project, plot_id) if f.model.kind != "predefined"}
    if to_dates and _fits_of(project, plot_id):
        steps += [
            SetField(fit.id, ("result",), None) for fit in _fits_of(project, plot_id)
        ]
        return Macro(_describe(axis, conversion), steps)
    plot_after = _after(project, steps)
    check_computable(plot_after, plot_id, data)
    if getattr(plot, "normalize", None) is not None:
        steps += _normalised_axis_follows(plot_after, plot, plot_id, data)
    return _with_fits_again(
        project, plot_id, _describe(axis, conversion), steps, data, may_fail=own
    )


def set_range(
    project: Project,
    plot_id: str,
    x_range: tuple[float, float] | None,
    data: DataProvider,
) -> Macro:
    """Use only the plot's rows with x in `x_range` (None: every row). A
    FitError, changing nothing, if a fit of the plot then fails."""
    plot = _plot(project, plot_id)
    text = "Use every row"
    if x_range is not None:
        dates = (
            isinstance(plot, LinePlot | ScatterPlot | ErrorbarPlot)
            and plot.x_conversion is None
            and _holds_times(plot, "x", data)
        )
        low, high = (date_text(e) if dates else f"{e:g}" for e in x_range)
        text = f"Use only x from {low} to {high}"
    steps: list[Command] = [SetField(plot_id, ("x_range",), x_range)]
    check_computable(_after(project, steps), plot_id, data)
    return _with_fits_again(project, plot_id, text, steps, data)


PROCESSING = {
    "smoothing": "Smooth the values",
    "normalize": "Normalise the y values",
}
"""The settings of a plot that compute from its data, and what turning each on
is called."""


def set_processing(
    project: Project, plot_id: str, name: str, value, data: DataProvider
) -> Macro:
    """Set `name`, one of PROCESSING, and fit the plot's fits again, as one
    step. Normalising takes the y axis along, as a unit does. A FitError,
    changing nothing, if it cannot be computed from the data or a fit then
    fails."""
    plot = _plot(project, plot_id)
    if name not in type(plot).model_fields:
        raise FitError(f"a {plot.kind} plot has no {name}")
    text = PROCESSING[name]
    if value is None:
        text = {"smoothing": "Remove the smoothing", "normalize": "Stop normalising"}[
            name
        ]
    steps: list[Command] = [SetField(plot_id, (name,), value)]
    staging = project.model_copy(deep=True)
    for step in steps:
        step.apply(staging)
    changed = _plot(staging, plot_id)
    if value is not None:  # taking a setting off is never refused
        check_computable(staging, plot_id, data)
    if name == "normalize":
        steps += _start_values_afresh(project, plot_id)
        steps += _normalised_axis(project, plot, changed, data)
    return _with_fits_again(
        project,
        plot_id,
        text,
        steps,
        data,
        may_fail=_fits_that_may_fail(project, plot_id, value),
    )


def _fits_that_may_fail(project: Project, plot_id: str, value) -> set[str]:
    """Taking a setting off is never refused, also where a fit then fails."""
    if value is not None:
        return set()
    return {fit.id for fit in _fits_of(project, plot_id)}


def _start_values_afresh(project: Project, plot_id: str) -> list[Command]:
    """Start values in the old units would mislead the fit, with a result or
    without, also where it then fails: they are not left lying for a later fit
    to start from. Held ones are the user's and stay as typed. An own formula
    keeps them all: nothing can be guessed for it, and from ones it can
    "converge" to nonsense."""
    steps: list[Command] = []
    for fit in _fits_of(project, plot_id):
        held = {k: v for k, v in fit.initial_values.items() if k in fit.fixed}
        if fit.model.kind == "predefined" and held != fit.initial_values:
            steps.append(SetField(fit.id, ("initial_values",), held))
    return steps


def _normalised_move(old, new, data):
    """(remap, rescale) from the y values `old` shows to those `new` does, which
    differ by a factor and an offset: normalising, the x unit under an area, or
    a unit with an offset. None if either cannot be computed or nothing says."""
    try:
        before, after = (
            plot_data(p.model_copy(update={"reduction": None}), data).y
            for p in (old, new)
        )
    except (FitError, DataError):
        return None
    finite = np.isfinite(before) & np.isfinite(after)
    if not finite.any():
        return None
    was, becomes = before[finite], after[finite]
    low, high = int(np.argmin(was)), int(np.argmax(was))
    if was[high] == was[low]:
        return None
    factor = float((becomes[high] - becomes[low]) / (was[high] - was[low]))
    offset = float(becomes[low] - factor * was[low])
    if abs(offset) <= 1e-12 * float(np.abs(becomes).max()):
        offset = 0.0  # rounding, where it is a factor alone

    def remap(value: float) -> float:
        return float(factor * value + offset)

    def rescale(width: float) -> float:
        return float(abs(factor) * width)

    return remap, rescale


def _normalised_axis_follows(project, old, plot_id: str, data) -> list[Command]:
    """The y axis of a normalised plot follows its values where a change of
    units moves them; `project` is as it is after that change."""
    new = _plot(project, plot_id)
    move = _normalised_move(old, new, data)
    if move is None or all(move[0](v) == v for v in (0.0, 1.0)):
        return []
    return _axis_follows(
        project, new, "y", None, None, *move, lambda panel_id, field: False
    )


def _normalised_axis(project: Project, old, new, data) -> list[Command]:
    """The y axis follows into normalised values and out of them: no unit, and
    what is typed on it converted. A unit typed on the axis does not come back,
    only that of the plot's conversion: as with a unit, the file's own is not
    known here."""
    axes = _panel_of(project, old.id)
    right = old.axis == "right" and axes.y_right is not None
    spec = axes.y_right if right else axes.y
    move = _normalised_move(old, new, data)
    if move is None:
        return []

    unit = old.y_conversion.unit if old.y_conversion else None
    was, becomes = None, None
    if old.normalize is None and spec.unit is not None:
        was = Conversion(unit=spec.unit)
    elif new.normalize is None and unit is not None:
        becomes = Conversion(unit=unit)
    return _axis_follows(
        project, old, "y", was, becomes, *move, lambda panel_id, field: False
    )


ALLAN_POINTS = ("values", "data_type", "sample_interval", "time", "taus", "error_bars")
"""What an Allan deviation's points and error bars are computed from: changing
one changes what a fit of it runs on."""


def set_allan_field(
    project: Project, plot_id: str, name: str, value, data: DataProvider, text: str
) -> Macro:
    """Set `name` of an Allan deviation and fit each fit of it again, as one
    step (decision 0064). A FitError, changing nothing, if a fit then fails."""
    _plot(project, plot_id)
    return _with_fits_again(
        project, plot_id, text, [SetField(plot_id, (name,), value)], data
    )


def _column_of(plot, axis: str):
    return getattr(plot, "values" if isinstance(plot, Histogram) else axis)


def _holds_times(plot, axis: str, data) -> bool:
    if isinstance(plot, AllanDeviationPlot):
        return False  # its axes are τ and σ
    return np.asarray(data(_column_of(plot, axis))).dtype.kind == "M"


def _time_mapping(raw: np.ndarray, old, new):
    """`_mapping` for a column of times: dates are days since 1970, a
    conversion counts from the earliest time."""
    filled = raw[~np.isnat(raw)]
    first = float(convert(filled.min(), None)) if filled.size else 0.0
    (old_factor, old_offset), (new_factor, new_offset) = linear(old), linear(new)

    def remap(value: float) -> float:
        if old is None:
            seconds = (value - first) * 86400
        else:
            seconds = (value - old_offset) / old_factor
        if new is None:
            return float(first + seconds / 86400)
        return float(seconds * new_factor + new_offset)

    def rescale(width: float) -> float:
        seconds = width * 86400 if old is None else width / old_factor
        return float(seconds / 86400 if new is None else seconds * new_factor)

    return remap, rescale


def _mapping(plot, axis: str, old, new, data):
    """Functions taking a value, and a width such as a tick step, from the old
    shown units to the new."""
    if isinstance(plot, AllanDeviationPlot):
        old_start = new_start = 0.0  # τ starts at τ0 whatever the conversion says
    else:
        raw = np.asarray(data(_column_of(plot, axis)))
        if raw.dtype.kind == "M":
            return _time_mapping(raw, old, new)
        old_start, new_start = start(raw, old), start(raw, new)
    (old_factor, old_offset), (new_factor, new_offset) = linear(old), linear(new)

    def remap(value: float) -> float:
        back = (value - old_offset) / old_factor + old_start - new_start
        return float(back * new_factor + new_offset)

    def rescale(width: float) -> float:
        return float(width / old_factor * new_factor)

    return remap, rescale


def check_computable(project: Project, plot_id: str, data) -> None:
    """A FitError if what the plot computes from its data cannot be, after a
    change of what it uses."""
    plot = _plot(project, plot_id)
    if processes(plot):
        plot_data(plot, data)


def _after(project: Project, steps: list[Command]) -> Project:
    staging = project.model_copy(deep=True)
    for step in steps:
        step.apply(staging)
    return staging


def default_smoothing(plot, data) -> Smoothing:
    """The smoothing a plot starts with: 11 points of order 3, fewer where the
    plot has not as many."""
    bare = plot.model_copy(
        update={"smoothing": None, "normalize": None, "reduction": None}
    )
    count = int(measured(bare, plot_data(bare, data)).sum())
    window = min(11, count if count % 2 else count - 1)
    if window < 3:
        raise FitError(f"smoothing needs at least 3 points; the plot has {count}")
    return Smoothing(window=window, order=min(3, window - 1))


def changed_smoothing(how: Smoothing, name: str, value) -> dict:
    """The settings of `how` with `name` set to `value`. Choosing Savitzky-Golay
    lowers an order that the window does not take, which could not be edited
    while it was a moving average."""
    changed = {**how.model_dump(), name: value}
    if name == "method" and value == "savgol":
        changed["order"] = min(changed["order"], changed["window"] - 1)
    return changed


def _always(panel_id: str, field: str) -> bool:
    return True


def _kept_for_dates(project, plot, axis: str, old, new, data):
    """Whether the axis `field` of a panel stays as it is, by (panel id,
    field): where it shows the dates of other plots before or after the change,
    what is typed on it are dates and stays so."""
    if not isinstance(plot, LinePlot | ScatterPlot | ErrorbarPlot):
        return lambda panel_id, field: False
    if not _holds_times(plot, axis, data):
        return lambda panel_id, field: False
    after = project.model_copy(deep=True)
    SetField(plot.id, (f"{axis}_conversion",), new).apply(after)
    is_time = time_columns_of(project)

    def on_dates(model: Project, panel_id: str, field: str) -> bool:
        return any(
            date_axis(figure, i, field, is_time)
            for figure in model.figures
            for i, panel in enumerate(figure.axes)
            if panel.id == panel_id
        )

    def keeps(panel_id: str, field: str) -> bool:
        return (old is not None and on_dates(project, panel_id, field)) or (
            new is not None and on_dates(after, panel_id, field)
        )

    return keeps


def _axis_follows(
    project, plot, axis, old, new, remap, rescale, keeps
) -> list[Command]:
    axes = _panel_of(project, plot.id)
    fitted = {
        a.id: a.target
        for figure in project.figures
        for panel in figure.axes
        for a in panel.artists
        if isinstance(a, FitCurve)
    }

    def tied(a) -> bool:
        """Whether `a` shows the converted plot's numbers."""
        if isinstance(a, ResidualPlot):
            return fitted.get(a.target) == plot.id
        return a.id == plot.id

    def other_data(a) -> bool:
        return isinstance(a, (*DATA_PLOTS, ResidualPlot)) and not tied(a)

    def follow(panels, field, side, move) -> list[Command]:
        """The axis that `panels` share. A panel follows, its unit's text and
        what is typed on it converted by `move`, unless it shows other data
        against the axis. A panel with neither the plot nor its residuals
        follows only if no panel of the axis shows other data."""
        if keeps(panels[0].id, field):
            return []
        standing = {
            panel.id: (lambda a, panel=panel: axis == "x" or _side(panel, a) == side)
            for panel in panels
        }
        group_alone = not any(
            other_data(a) and standing[panel.id](a)
            for panel in panels
            for a in panel.artists
        )
        planned = []
        for panel in panels:
            here = [a for a in panel.artists if standing[panel.id](a)]
            own = any(a.id == plot.id for a in panel.artists)
            follows = not any(map(other_data, here)) and (
                group_alone or any(map(tied, here))
            )
            spec: AxisSpec = getattr(panel, field)
            changes: dict = {}
            # What the axis shows for the old setting: its unit, unless that
            # gave one. The plot's own panel is renamed beside other data too.
            given = old is not None and old.unit is not None
            old_unit = old.unit if given else spec.unit
            if own or follows:
                if new is None:
                    if given and spec.unit == old.unit:
                        changes["unit"] = None  # the file's unit is not known here
                elif new.unit is not None and spec.unit in (None, old_unit):
                    changes["unit"] = new.unit
            if follows:
                if spec.limits is not None:
                    changes["limits"] = _ends(spec.limits, move)
                if spec.ticks is not None:
                    changes["ticks"] = [move(t) for t in spec.ticks]
                if spec.major_step is not None:
                    changes["major_step"] = rescale(spec.major_step)
                if spec.symlog_linthresh is not None:
                    changes["symlog_linthresh"] = rescale(spec.symlog_linthresh)
                # A conversion rises with the value, so breaks stay in order.
                # Panel by panel, like the range: beside data in other units
                # no numbers suit the axis, and once each is converted all do.
                if spec.breaks:
                    changes["breaks"] = [_ends(ends, move) for ends in spec.breaks]
            planned.append((panel, spec, changes, follows))
        _drop_prefix(planned, None if new is None else new.unit)
        steps: list[Command] = []
        for panel, spec, changes, follows in planned:
            if changes:
                changed = spec.model_copy(update=changes)
                steps.append(SetField(panel.id, (field,), changed))
            if follows:
                steps += _marks_follow(panel, axis, standing[panel.id], move)
        return steps

    def stands(panel, a) -> tuple[str, str, list[Axes]]:
        """(field, side, the panels sharing it) of the axis `a` is drawn on."""
        if axis == "x":
            return "x", "left", _sharing(project, panel, "x")
        side = _side(panel, a)
        if side == "right":
            return "y_right", side, [panel]
        return "y", side, _sharing(project, panel, "y")

    field, side, panels = stands(axes, plot)
    steps = follow(panels, field, side, remap)
    # Residuals of the plot's fits show its numbers too, and may have axes of
    # their own. In y they are differences, which an offset does not move.
    done = {(panel.id, field) for panel in panels}
    for figure in project.figures:
        for panel in figure.axes:
            for a in panel.artists:
                if not isinstance(a, ResidualPlot) or not tied(a):
                    continue
                there, side, group = stands(panel, a)
                if (panel.id, there) in done:
                    continue
                done |= {(other.id, there) for other in group}
                steps += follow(group, there, side, remap if axis == "x" else rescale)
    return steps


def _drop_prefix(planned, unit: str | None) -> None:
    """Take the SI prefix off a shared axis whose unit is renamed to `unit`: it
    was chosen for the old one, and an "m" beside "mV" reads "mmV".

    The axis has one formatter, so a prefix left on one panel scales the numbers
    of all: it goes from every panel or from none, and only once each panel
    that has one shows `unit`."""
    texts = [(spec, changes.get("unit", spec.unit)) for _, spec, changes, _ in planned]
    stated = any(spec.unit is not None for spec, _ in texts)
    # Naming a panel whose unit is stated on another one renames nothing.
    renamed = any(
        text != spec.unit and (spec.unit is not None or not stated)
        for spec, text in texts
    )
    agreed = all(text == unit for spec, text in texts if spec.prefix is not None)
    if renamed and agreed:
        for _, spec, changes, _ in planned:
            if spec.prefix is not None:
                changes["prefix"] = None


def _side(panel: Axes, artist) -> str:
    """The y axis `artist` is drawn against: without a right one, the left."""
    right = artist.axis == "right" and panel.y_right is not None
    return "right" if right else "left"


def _sharing(project: Project, axes: Axes, field: str) -> list[Axes]:
    """The panels whose `field` axis is one with that of `axes`, itself too."""
    for figure in project.figures:
        for i, panel in enumerate(figure.axes):
            if panel.id == axes.id:
                return [figure.axes[j] for j in sharing_group(figure, i, field)]
    return [axes]


def _marks_follow(axes: Axes, axis: str, same_side, remap) -> list[Command]:
    """The reference lines, shaded ranges and notes placed on the axis, and the
    x range a function is given; its formula stays as written."""
    across = "vertical" if axis == "x" else "horizontal"
    index = 0 if axis == "x" else 1
    steps: list[Command] = []
    for mark in axes.artists:
        if not same_side(mark):
            continue
        if isinstance(mark, FunctionPlot):
            if axis == "x" and mark.curve_range is not None:
                ends = _ends(mark.curve_range, remap)
                steps.append(SetField(mark.id, ("curve_range",), ends))
        elif isinstance(mark, ReferenceLine) and mark.orientation == across:
            steps.append(SetField(mark.id, ("at",), remap(mark.at)))
        elif isinstance(mark, ShadedSpan) and mark.orientation == across:
            steps.append(SetField(mark.id, ("start",), remap(mark.start)))
            steps.append(SetField(mark.id, ("end",), remap(mark.end)))
        elif isinstance(mark, Annotation) and mark.coords == "data":
            for part in ("position", "arrow_to"):
                point = getattr(mark, part)
                if point is not None:
                    moved = list(point)
                    moved[index] = remap(point[index])
                    steps.append(SetField(mark.id, (part,), tuple(moved)))
    return steps


def _with_fits_again(project, plot_id, text, steps, data, may_fail=()) -> Macro:
    """`steps`, then each fit of the plot run again on the changed project."""
    staging = project.model_copy(deep=True)
    for step in steps:
        step.apply(staging)
    for fit in _fits_of(staging, plot_id):
        steps += refit_in_edit(project, staging, fit, data, fit.id in may_fail)
    return Macro(text, steps)


def _describe(axis: str, conversion: Conversion | None) -> str:
    if conversion is None:
        return f"Show {axis} as in the file"
    if conversion.unit:
        return f"Show {axis} in {conversion.unit}"
    if conversion.formula:
        return f"Show {axis} as {conversion.formula}"
    return f"Show {axis} scaled by {conversion.factor:g}"


def _ends(ends: tuple[float, float], remap) -> tuple[float, float]:
    return (remap(ends[0]), remap(ends[1]))


def _fits_of(project: Project, plot_id: str) -> list[FitCurve]:
    return [
        artist
        for figure in project.figures
        for axes in figure.axes
        for artist in axes.artists
        if isinstance(artist, FitCurve) and artist.target == plot_id
    ]


def _panel_of(project: Project, oid: str) -> Axes:
    for figure in project.figures:
        for axes in figure.axes:
            if any(a.id == oid for a in axes.artists):
                return axes
    raise FitError(f"no plot with id {oid!r}")


def _plot(project: Project, plot_id: str):
    try:
        plot = find(project, plot_id)
    except CommandError as exc:
        raise FitError(str(exc)) from exc
    if not isinstance(plot, CONVERTIBLE):
        raise FitError(f"{plot_id!r} is not a plot with units or a range")
    return plot
