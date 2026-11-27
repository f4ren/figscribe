"""A fit follows what it was fitted to (decision 0076).

The window draws a fit's stored result, while the generated script fits again.
So whenever something a fit is run on changes, the fit is run again as part of
the same step, however the change is made: every change from the window and
the assistant passes through here. A fit that cannot be run then is left not
fitted, which draws nothing, rather than with the old result.
"""

from __future__ import annotations

import copy
from pathlib import Path

from figscribe.commands import Command, Macro, SetField
from figscribe.fit import FitError, refit
from figscribe.io import DataError, load_data
from figscribe.io.refresh import source_state
from figscribe.model import FitCurve, Project
from figscribe.model.validate import FIT_TARGETS, data_refs

DATA_FIELDS = (
    "x",
    "y",
    "xerr",
    "yerr",
    "x_conversion",
    "y_conversion",
    "x_range",
    "left_out",
    "reduction",
    "values",
    "data_type",
    "sample_interval",
    "time",
    "taus",
    "error_bars",
)
"""The fields of a plot that decide the points a fit of it is run on."""

LOOK_FIELDS = (
    "id",
    "label",
    "visible",
    "zorder",
    "alpha",
    "axis",
    "kind",
    "color",
    "linestyle",
    "linewidth",
    "marker",
    "markersize",
    "size",
    "edgecolor",
    "capsize",
    "elinewidth",
    "band",
    "left_out_color",
    "left_out_marker",
    "left_out_linestyle",
    "left_out_note",
)
"""The other fields of such a plot: they change how it looks only."""

INPUTS = (
    "target",
    "model",
    "initial_values",
    "fixed",
    "parameter_bounds",
    "fit_range",
)
"""The fields of a fit that its result comes from."""

OWN_FIELDS = tuple(name for name in FitCurve.model_fields if name not in INPUTS)
"""The rest of a fit: its result and its look."""


def fits_follow(project: Project, command: Command, base_dir: str | Path) -> Command:
    """`command`, and after it each fit run again whose inputs it changes and
    whose result it does not set itself: one step. `command` unchanged where
    there is none."""
    before = {
        fit.id: (_inputs(project, fit), repr(fit.result))
        for fit in _fits(project)
        if fit.result is not None
    }
    if not before:
        return command
    staging = project.model_copy(deep=True)
    copy.deepcopy(command).apply(staging)
    steps: list[Command] = []
    for fit in _fits(staging):
        if fit.id not in before:
            continue
        inputs, result = before[fit.id]
        if repr(fit.result) != result:
            continue  # the command has seen to it
        new = _inputs(staging, fit)
        if new == inputs or not _readable(staging, fit, base_dir):
            continue
        for step in _again(staging, fit, base_dir, data_changed=new[1:] != inputs[1:]):
            step.apply(staging)
            steps.append(step)
    if not steps:
        return command
    return Macro(command.description, [command, *steps])


def _fits(project: Project) -> list[FitCurve]:
    return [
        artist
        for figure in project.figures
        for axes in figure.axes
        for artist in axes.artists
        if isinstance(artist, FitCurve)
    ]


def _target(project: Project, fit: FitCurve):
    return next(
        (
            artist
            for figure in project.figures
            for axes in figure.axes
            for artist in axes.artists
            if artist.id == fit.target and isinstance(artist, FIT_TARGETS)
        ),
        None,
    )


def _sources(project: Project, plot) -> list:
    used = {source for _, source in data_refs(plot)}
    return [source for source in project.sources if source.id in used]


def _inputs(project: Project, fit: FitCurve) -> tuple[str, str, str]:
    """What the fit's result comes from, in three parts: its model and what it
    was told, then its plot's points, then the files those are in. Told from
    the model alone, without reading data."""
    told = repr(fit.model_dump(include=set(INPUTS) - {"model"}))
    plot = _target(project, fit)
    if plot is None:
        return told, repr(fit.model), ""
    points = repr(plot.model_dump(include=set(DATA_FIELDS)))
    # Not the path: the same bytes elsewhere give the same result.
    files = repr([s.model_dump(exclude={"path"}) for s in _sources(project, plot)])
    return told, repr(fit.model), points + files


def _readable(project: Project, fit: FitCurve, base_dir: str | Path) -> bool:
    """Whether the files the fit reads are the ones imported. Only then does a
    failure to fit say something about the fit."""
    plot = _target(project, fit)
    return plot is not None and all(
        source_state(source, base_dir) == "ok" for source in _sources(project, plot)
    )


def _again(
    project: Project, fit: FitCurve, base_dir: str | Path, data_changed: bool
) -> list[Command]:
    """The steps that fit `fit` again; that leave it not fitted if it cannot."""
    data = load_data(project, base_dir)
    held = {k: v for k, v in fit.initial_values.items() if k in fit.fixed}
    # From the values it started from, or guessed anew. Where the points or the
    # model are others, a guess from them goes first; nothing can be guessed
    # for an own formula.
    starts = [None, held]
    if data_changed and fit.model.kind == "predefined":
        starts.reverse()
    for start in starts:
        trial = project.model_copy(deep=True)
        steps: list[Command] = []
        if start is not None and start != fit.initial_values:
            steps.append(SetField(fit.id, ("initial_values",), start))
            steps[0].apply(trial)
        try:
            again = refit(trial, fit.id, data)
        except (FitError, DataError, ValueError, KeyError, IndexError):
            continue
        result = next(s for s in again.steps if s.path == ("result",)).value
        if result.converged:
            return [*steps, *again.steps]
    return [SetField(fit.id, ("result",), None)]
