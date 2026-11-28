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
from figscribe.fit import FitError, keeps, refit
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
    "baseline",
    "smoothing",
    "normalize",
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
    told: set[str] = set()  # fits the command gives start values, to be used
    for part in parts:
        part.apply(staging)
        if isinstance(part, SetField) and part.path[0] == "initial_values":
            told.add(part.target)
        if fit_id := _result_of(part):
            told.discard(fit_id)
            # Seen to as the inputs are now; a later part may change them yet.
            fit = next(f for f in _fits(staging) if f.id == fit_id)
            seen[fit_id] = (_inputs(staging, fit), _paths(staging, fit))
    steps: list[Command] = []
    data = None  # one for all the fits: each file is read once
    for fit in _fits(staging):
        if fit.id not in seen:
            continue  # new, and not fitted by the command
        inputs, paths = seen[fit.id]
        new = _inputs(staging, fit)
        # One left not fitted is tried again once its file is found elsewhere,
        # too: Locate may change nothing but the path.
        moved = fit.drawn_result() is None and _paths(staging, fit) != paths
        if new == inputs and not moved:
            continue
        again, why = [], "the files cannot be read"
        if _readable(staging, fit, base_dir):
            data = data or load_data(staging, base_dir)
            if fit.id in told:
                again, why = run_again(staging, fit, data, (fit.initial_values,))
            else:
                again, why = run_again(staging, fit, data, _starts(fit, inputs, new))
        if why is not None and fit.result is not None:
            again = [SetField(fit.id, ("result",), None)]
        for step in again:
            step.apply(staging)
            steps.append(step)
    if not steps:
        return command
    return Macro(command.description, [command, *steps])


def guess_first(fit: FitCurve) -> tuple[dict, ...]:
    """The starts to try where the values `fit` started from cannot be right:
    another model, or another file. Nothing can be guessed for an own formula,
    so it keeps its values."""
    if fit.model.kind != "predefined":
        return (fit.initial_values,)
    return (_held(fit), fit.initial_values)


def _starts(fit: FitCurve, inputs: tuple, new: tuple) -> tuple[dict, ...]:
    """The starts to try after a change from `inputs` to `new`: the values
    there are first, which may have been typed, unless the model is another."""
    if new[1] != inputs[1]:
        return guess_first(fit)
    if fit.model.kind != "predefined":
        return (fit.initial_values,)
    return (fit.initial_values, _held(fit))


def _held(fit: FitCurve) -> dict:
    """The start values that stay when the others are guessed."""
    return {k: v for k, v in fit.initial_values.items() if k in fit.fixed}


def run_again(
    project: Project, fit: FitCurve, data, starts: tuple[dict, ...]
) -> tuple[list[Command], str | None]:
    """The steps that fit `fit` to `data`, trying `starts` in turn, and None;
    or no steps, and why it cannot be fitted. The start values change only
    where the fit succeeds."""
    why = None
    for start in starts:
        trial = project.model_copy(deep=True)
        SetField(fit.id, ("initial_values",), start).apply(trial)
        try:
            again = refit(trial, fit.id, data)
        except (FitError, DataError, OSError, ValueError, KeyError, IndexError) as exc:
            # A KeyError's text is its message in quotes; others are as they are.
            text = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
            why = why or str(text).rstrip(".")
            continue
        result = next(s for s in again.steps if s.path == ("result",)).value
        if keeps(fit.model, fit.drawn_result(), result):
            return again.steps, None
        why = why or (
            "the data do not decide its parameters"
            if result.converged
            else "the fit did not converge"
        )
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
    try:
        return plot is not None and all(
            source_state(source, base_dir) == "ok" for source in _sources(project, plot)
        )
    except OSError:  # there, but it cannot be opened
        return False
