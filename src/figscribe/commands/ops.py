"""User-level actions, each built from primitives as one undo step."""

from __future__ import annotations

from typing import Any

from figscribe.commands.core import CommandError, Macro, RemoveItem, noun, walk
from figscribe.model import FitCurve, Project, ResidualPlot


def remove_artist(project: Project, artist_id: str) -> Macro:
    """Remove an artist together with the fits and residuals that refer to it.

    Removing a data artist removes every FitCurve on it and their ResidualPlots;
    removing a fit removes its residuals. An Axes left empty stays: changing the
    layout as a side effect would be hard to predict.
    """
    artist, axes = _locate(project, artist_id, "artists")
    steps = _remove_dependents(project, {artist_id})
    steps.append(RemoveItem(axes.id, "artists", artist_id))
    return Macro(f"Remove {noun(artist)}", steps)


def remove_axes(project: Project, axes_id: str) -> Macro:
    """Remove an Axes with its artists, and whatever elsewhere refers to them.

    The grid keeps its size; only the panel goes.
    """
    axes, figure = _locate(project, axes_id, "axes")
    inside = {a.id for a in axes.artists}
    steps = [
        step
        for step in _remove_dependents(project, inside)
        if step.parent != axes_id  # those go with the axes
    ]
    steps.append(RemoveItem(figure.id, "axes", axes_id))
    return Macro("Remove axes", steps)


def _remove_dependents(project: Project, removed: set[str]) -> list[RemoveItem]:
    """RemoveItems for every artist that refers, directly or via a fit, to `removed`.

    Residuals come before their fits, so undo restores fits first.
    """
    artists = [(a, axes) for a, axes, f in walk(project) if f == "artists"]
    fits = [
        (a, axes)
        for a, axes in artists
        if isinstance(a, FitCurve) and a.target in removed and a.id not in removed
    ]
    fit_ids = {a.id for a, _ in fits} | {
        a.id for a, _ in artists if isinstance(a, FitCurve) and a.id in removed
    }
    residuals = [
        (a, axes)
        for a, axes in artists
        if isinstance(a, ResidualPlot) and a.target in fit_ids and a.id not in removed
    ]
    return [RemoveItem(axes.id, "artists", a.id) for a, axes in [*residuals, *fits]]


def _locate(project: Project, oid: str, field: str) -> tuple[Any, Any]:
    """The object with id `oid` held in a list named `field`, and its owner."""
    for obj, parent, f in walk(project):
        if obj.id == oid and f == field:
            return obj, parent
    kind = "artist" if field == "artists" else field
    raise CommandError(f"no {kind} with id {oid!r}")
