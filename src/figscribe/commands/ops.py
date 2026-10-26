"""User-level actions, each built from primitives as one undo step."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from figscribe.commands.core import (
    CommandError,
    InsertItem,
    Macro,
    RemoveItem,
    SetField,
    noun,
    walk,
)
from figscribe.model import (
    Axes,
    Figure,
    FitCurve,
    GridLayout,
    Inset,
    Project,
    ResidualPlot,
    new_id,
)
from figscribe.model.validate import data_refs

Side = Literal["right", "left", "above", "below", "inset"]


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
    going = [axes, *(a for a in figure.axes if a.inset and a.inset.parent == axes_id)]
    panels = {a.id for a in going}
    inside = {artist.id for a in going for artist in a.artists}
    steps = [
        step
        for step in _remove_dependents(project, inside)
        if step.parent not in panels  # those go with their axes
    ]
    steps += [RemoveItem(figure.id, "axes", a.id) for a in reversed(going)]
    return Macro("Remove axes", steps)


def remove_source(project: Project, source_id: str) -> Macro:
    """Remove a data file from the project, with the plots that draw from it
    and their fits and residuals. The file itself stays where it is."""
    source, _ = _locate(project, source_id, "sources")
    plots = {
        artist.id: axes
        for artist, axes, field in walk(project)
        if field == "artists" and any(ref == source_id for _, ref in data_refs(artist))
    }
    steps = _remove_dependents(project, set(plots))
    steps += [RemoveItem(axes.id, "artists", oid) for oid, axes in plots.items()]
    steps.append(RemoveItem(None, "sources", source_id))
    return Macro(f"Remove {Path(source.path).name}", steps)


def add_figure(project: Project, after: str | None = None) -> tuple[Macro, Figure]:
    """A new figure with one empty panel, after the figure `after` (default:
    at the end). It takes over that figure's look, or the last one's: size,
    fonts, ticks and panel letters, in which a project's figures agree."""
    index = len(project.figures)
    if after is not None:
        index = _figure_index(project, after) + 1
    content = {
        "id": new_id(),
        "name": _free_name(project, "Figure {}", index + 1),
        "layout": GridLayout(),
        "axes": [Axes()],
    }
    like = project.figures[index - 1] if project.figures else Figure()
    figure = like.model_copy(deep=True, update=content)
    return Macro("Add a figure", [InsertItem(None, "figures", figure, index)]), figure


def duplicate_figure(project: Project, figure_id: str) -> tuple[Macro, Figure]:
    """A copy of the figure, right after it, with ids of its own: its fits,
    residuals and insets refer to its own plots and panels, its plots to the
    same data."""
    index = _figure_index(project, figure_id)
    copy = project.figures[index].model_copy(deep=True)
    renamed = {copy.id: new_id()}
    for axes in copy.axes:
        renamed[axes.id] = new_id()
        for artist in axes.artists:
            renamed[artist.id] = new_id()
    copy.id = renamed[copy.id]
    for axes in copy.axes:
        axes.id = renamed[axes.id]
        if axes.inset is not None:
            axes.inset.parent = renamed[axes.inset.parent]
        for artist in axes.artists:
            artist.id = renamed[artist.id]
            if isinstance(artist, FitCurve | ResidualPlot):
                artist.target = renamed.get(artist.target, artist.target)
    name = project.figures[index].name
    first = f"{name} (copy)"
    copy.name = (
        first
        if not any(f.name == first for f in project.figures)
        else _free_name(project, f"{name} (copy {{}})", 2)
    )
    step = InsertItem(None, "figures", copy, index + 1)
    return Macro(f"Duplicate {name}", [step]), copy


def remove_figure(project: Project, figure_id: str) -> Macro:
    """Remove a figure with its panels; a project keeps at least one."""
    figure = project.figures[_figure_index(project, figure_id)]
    if len(project.figures) == 1:
        raise CommandError("a project keeps at least one figure")
    inside = {artist.id for axes in figure.axes for artist in axes.artists}
    panels = {axes.id for axes in figure.axes}
    steps = [
        step
        for step in _remove_dependents(project, inside)
        if step.parent not in panels  # those go with the figure
    ]
    steps.append(RemoveItem(None, "figures", figure_id))
    return Macro(f"Remove {figure.name}", steps)


def _figure_index(project: Project, figure_id: str) -> int:
    for i, figure in enumerate(project.figures):
        if figure.id == figure_id:
            return i
    raise CommandError(f"no figure with id {figure_id!r}")


def _free_name(project: Project, pattern: str, start: int) -> str:
    """`pattern` with the first number from `start` that no figure has."""
    taken = {f.name for f in project.figures}
    n = start
    while pattern.format(n) in taken:
        n += 1
    return pattern.format(n)


def add_panel(project: Project, axes_id: str, side: Side) -> tuple[Macro, Axes]:
    """A new, empty panel next to the panel `axes_id`, or inside it.

    Beside the panel, free cells of the grid are used if there are any;
    otherwise a row or column is inserted there, the panels behind it move
    along and those spanning across it grow. The figure keeps its size.
    """
    axes, figure = _locate(project, axes_id, "axes")
    if axes.inset is not None:
        raise CommandError("an inset cannot have panels beside or inside it")
    if side == "inset":
        new = Axes(inset=Inset(parent=axes_id))
        return Macro("Add inset", [InsertItem(figure.id, "axes", new)]), new
    across = side in ("left", "right")
    start, span = (axes.col, axes.colspan) if across else (axes.row, axes.rowspan)
    lines = (
        range(axes.row, axes.row + axes.rowspan)
        if across
        else range(axes.col, axes.col + axes.colspan)
    )
    size = figure.layout.cols if across else figure.layout.rows
    target = start + span if side in ("right", "below") else start - 1
    steps: list = []
    if not (0 <= target < size and _free(figure, across, target, lines)):
        target = start + span if side in ("right", "below") else start
        steps = _insert_line(figure, across, target)
    place = (
        {"row": axes.row, "rowspan": axes.rowspan, "col": target}
        if across
        else {"col": axes.col, "colspan": axes.colspan, "row": target}
    )
    new = Axes(**place)
    steps.append(InsertItem(figure.id, "axes", new))
    where = {"right": "to the right", "left": "to the left"}.get(side, side)
    return Macro(f"Add panel {where}", steps), new


def _free(figure: Figure, across: bool, line: int, cells: range) -> bool:
    """Whether no grid panel covers `line` (a column if `across`, else a row)
    at any of `cells` (rows if `across`, else columns)."""
    for other in figure.axes:
        if other.inset is not None:
            continue
        mine = range(other.col, other.col + other.colspan)
        theirs = range(other.row, other.row + other.rowspan)
        if not across:
            mine, theirs = theirs, mine
        if line in mine and any(c in theirs for c in cells):
            return False
    return True


def _insert_line(figure: Figure, across: bool, at: int) -> list:
    """Steps that insert an empty column (`across`) or row at index `at`."""
    layout = figure.layout
    count, ratios_name = (
        ("cols", "width_ratios") if across else ("rows", "height_ratios")
    )
    ratios = getattr(layout, ratios_name)
    update = {count: getattr(layout, count) + 1}
    if ratios is not None:
        neighbour = ratios[at - 1] if at > 0 else ratios[0]
        update[ratios_name] = [*ratios[:at], neighbour, *ratios[at:]]
    steps: list = [SetField(figure.id, ("layout",), layout.model_copy(update=update))]
    position, span = ("col", "colspan") if across else ("row", "rowspan")
    for other in figure.axes:
        if other.inset is not None:
            continue
        first = getattr(other, position)
        if first >= at:
            steps.append(SetField(other.id, (position,), first + 1))
        elif first + getattr(other, span) > at:
            steps.append(SetField(other.id, (span,), getattr(other, span) + 1))
    return steps


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
    kind = {"artists": "artist", "sources": "data file"}.get(field, field)
    raise CommandError(f"no {kind} with id {oid!r}")
