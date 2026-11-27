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
    whose result it does not set itself afterwards: one step. `command`
    unchanged where there is none."""
    parts = list(_parts(copy.deepcopy(command)))
    if not _fits(project) and not any(_result_of(part) for part in parts):
        return command
    # By fit, its inputs and file paths as its result was last seen to.
    seen = {
        fit.id: (_inputs(project, fit), _paths(project, fit)) for fit in _fits(project)
    }
    staging = project.model_copy(deep=True)
    for part in parts:
        part.apply(staging)
        if fit_id := _result_of(part):
            # Seen to as the inputs are now; a later part may change them yet.
            fit = next(f for f in _fits(staging) if f.id == fit_id)
            seen[fit_id] = (_inputs(staging, fit), _paths(staging, fit))
    steps: list[Command] = []
    for fit in _fits(staging):
        if fit.id not in seen:
            continue  # new, and not fitted by the command
        inputs, paths = seen[fit.id]
        new = _inputs(staging, fit)
        # One left not fitted is tried again once its file is found elsewhere,
        # too: Locate may change nothing but the path.
        moved = fit.result is None and _paths(staging, fit) != paths
        if new == inputs and not moved:
            continue
        again, why = [], "the files cannot be read"
        if _readable(staging, fit, base_dir):
            data = load_data(staging, base_dir)
            again, why = run_again(staging, fit, data, new[1:] != inputs[1:])
        if why is not None and fit.result is not None:
            again = [SetField(fit.id, ("result",), None)]
        for step in again:
            step.apply(staging)
            steps.append(step)
    if not steps:
        return command
    return Macro(command.description, [command, *steps])


def run_again(
    project: Project, fit: FitCurve, data, data_changed: bool
) -> tuple[list[Command], str | None]:
    """The steps that fit `fit` to `data`, and None; or no steps, and why it
    cannot be fitted. The start values change only where the fit succeeds.

    A predefined model is tried from the values it started from and from a
    guess; where the points or the model are others (`data_changed`) the guess
    goes first. Nothing can be guessed for an own formula, so its values are
    the only start: ones must not take their place.
    """
    stored = fit.initial_values
    starts = [stored]
    if fit.model.kind == "predefined":
        guessed = {k: v for k, v in stored.items() if k in fit.fixed}
        starts = [guessed, stored] if data_changed else [stored, guessed]
    why = None
    for start in starts:
        trial = project.model_copy(deep=True)
        SetField(fit.id, ("initial_values",), start).apply(trial)
        try:
            again = refit(trial, fit.id, data)
        except (FitError, DataError, ValueError, KeyError, IndexError) as exc:
            why = why or str(exc).strip("'\"").rstrip(".")
            continue
        if next(s for s in again.steps if s.path == ("result",)).value.converged:
            return again.steps, None
        why = why or "the fit did not converge"
    return [], why


def _parts(command: Command):
    """The single changes `command` is made of, in order."""
    if isinstance(command, Macro):
        for step in command.steps:
            yield from _parts(step)
    else:
        yield command


def _result_of(part: Command) -> str | None:
    """The fit whose result `part` sets; None for any other change. Asked of
    the command, not of the values: a fit run again may come out as before."""
    if isinstance(part, SetField) and part.path == ("result",):
        return part.target
    return None


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


def _paths(project: Project, fit: FitCurve) -> list[str]:
    plot = _target(project, fit)
    return [] if plot is None else [s.path for s in _sources(project, plot)]


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
