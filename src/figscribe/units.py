"""Changing a plot's units or range as one undoable step (decision 0041).

Everything typed in a plot's shown units is converted along, so that the
same rows stay selected and the same places marked: its range, its fits'
ranges, and on its axis the limits, ticks, step and the reference lines,
shaded ranges and notes, unless another data plot is drawn against that
axis. The plot's fits are run again on the converted data, in the same step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np

from figscribe.commands import Command, CommandError, Macro, SetField, find
from figscribe.convert import start
from figscribe.fit import FitError, refit
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
    Histogram,
    ImagePlot,
    LinePlot,
    Project,
    ReferenceLine,
    ScatterPlot,
    ShadedSpan,
)

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
    file). A FitError, changing nothing, if a fit of the plot then fails."""
    plot = _plot(project, plot_id)
    field = f"{axis}_conversion"
    if field not in type(plot).model_fields:
        raise FitError(f"a {plot.kind} plot has no {axis} to convert")
    old = getattr(plot, field)
    remap, rescale = _mapping(plot, axis, old, conversion, data)

    steps: list[Command] = [SetField(plot_id, (field,), conversion)]
    if axis == "x" and plot.x_range is not None:
        steps.append(SetField(plot_id, ("x_range",), _ends(plot.x_range, remap)))
    for fit in _fits_of(project, plot_id):
        if axis == "x" and fit.fit_range is not None:
            steps.append(SetField(fit.id, ("fit_range",), _ends(fit.fit_range, remap)))
        # Start values in the old units would mislead the fit; held ones are
        # the user's and stay as typed.
        held = {k: v for k, v in fit.initial_values.items() if k in fit.fixed}
        if held != fit.initial_values:
            steps.append(SetField(fit.id, ("initial_values",), held))
    steps += _axis_follows(project, plot, axis, old, conversion, remap, rescale)
    return _with_fits_again(project, plot_id, _describe(axis, conversion), steps, data)


def set_range(
    project: Project,
    plot_id: str,
    x_range: tuple[float, float] | None,
    data: DataProvider,
) -> Macro:
    """Use only the plot's rows with x in `x_range` (None: every row). A
    FitError, changing nothing, if a fit of the plot then fails."""
    _plot(project, plot_id)
    text = (
        "Use every row"
        if x_range is None
        else f"Use only x from {x_range[0]:g} to {x_range[1]:g}"
    )
    steps: list[Command] = [SetField(plot_id, ("x_range",), x_range)]
    return _with_fits_again(project, plot_id, text, steps, data)


def _mapping(plot, axis: str, old, new, data):
    """Functions taking a value, and a width such as a tick step, from the old
    shown units to the new."""
    if isinstance(plot, AllanDeviationPlot):
        old_start = new_start = 0.0  # τ starts at τ0 whatever the conversion says
    else:
        column = getattr(plot, "values" if isinstance(plot, Histogram) else axis)
        raw = data(column)
        old_start, new_start = start(raw, old), start(raw, new)
    old_factor = old.factor if old is not None else 1.0
    new_factor = new.factor if new is not None else 1.0

    def remap(value: float) -> float:
        return float((value / old_factor + old_start - new_start) * new_factor)

    def rescale(width: float) -> float:
        return float(width / old_factor * new_factor)

    return remap, rescale


def _axis_follows(project, plot, axis, old, new, remap, rescale) -> list[Command]:
    axes = _panel_of(project, plot.id)
    field = "x" if axis == "x" else ("y_right" if plot.axis == "right" else "y")
    spec: AxisSpec | None = getattr(axes, field)
    if spec is None:
        return []
    same_side = (lambda a: True) if axis == "x" else (lambda a: a.axis == plot.axis)
    alone = not any(
        isinstance(a, DATA_PLOTS) and a.id != plot.id and same_side(a)
        for a in axes.artists
    )
    changes: dict = {}
    # What the axis shows for the old setting: its unit, unless that gave one.
    old_unit = old.unit if old is not None and old.unit is not None else spec.unit
    if new is None:
        if old is not None and old.unit is not None and spec.unit == old.unit:
            changes["unit"] = None  # the file's unit is not known here
    elif new.unit is not None and spec.unit in (None, old_unit):
        changes["unit"] = new.unit
    steps: list[Command] = []
    if alone:
        if spec.limits is not None:
            changes["limits"] = _ends(spec.limits, remap)
        if spec.ticks is not None:
            changes["ticks"] = [remap(t) for t in spec.ticks]
        if spec.major_step is not None:
            changes["major_step"] = rescale(spec.major_step)
        if spec.symlog_linthresh is not None:
            changes["symlog_linthresh"] = rescale(spec.symlog_linthresh)
        steps += _marks_follow(axes, axis, same_side, remap)
    if changes:
        steps.insert(0, SetField(axes.id, (field,), spec.model_copy(update=changes)))
    return steps


def _marks_follow(axes: Axes, axis: str, same_side, remap) -> list[Command]:
    """The reference lines, shaded ranges and notes placed on the axis."""
    across = "vertical" if axis == "x" else "horizontal"
    index = 0 if axis == "x" else 1
    steps: list[Command] = []
    for mark in axes.artists:
        if not same_side(mark):
            continue
        if isinstance(mark, ReferenceLine) and mark.orientation == across:
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


def _with_fits_again(project, plot_id, text, steps, data) -> Macro:
    """`steps`, then each fit of the plot run again on the changed project."""
    staging = project.model_copy(deep=True)
    for step in steps:
        step.apply(staging)
    for fit in _fits_of(staging, plot_id):
        again = refit(staging, fit.id, data)
        again.apply(staging)
        steps += again.steps
    return Macro(text, steps)


def _describe(axis: str, conversion: Conversion | None) -> str:
    if conversion is None:
        return f"Show {axis} as in the file"
    if conversion.unit:
        return f"Show {axis} in {conversion.unit}"
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
