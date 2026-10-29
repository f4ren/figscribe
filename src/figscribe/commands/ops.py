"""User-level actions, each built from primitives as one undo step."""

from __future__ import annotations

from collections.abc import Sequence
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


def remove_artists(project: Project, artist_ids: list[str]) -> Macro:
    """Remove several artists at once, each with what refers to it, as one
    undo step; one that goes with another already is not removed twice."""
    steps: list[RemoveItem] = []
    going: set[str] = set()
    for artist_id in artist_ids:
        if artist_id in going:
            continue
        new = [
            step
            for step in remove_artist(project, artist_id).steps
            if step.item_id not in going
        ]
        going |= {step.item_id for step in new}
        steps += new
    return Macro(f"Remove {len(artist_ids)} plots", steps)


STYLE = (
    "color",
    "marker",
    "markersize",
    "size",
    "edgecolor",
    "linestyle",
    "linewidth",
    "capsize",
    "elinewidth",
    "alpha",
)
"""How a plot looks, as "Style like" takes it over from another."""


def copy_style(project: Project, target_id: str, source_id: str) -> Macro:
    """Give the plot `target_id` the look of `source_id`: each style field
    both have, as far as the target can take the value (a line plot's "no
    marker" is not a marker for error bars)."""
    source, _ = _locate(project, source_id, "artists")
    macro = paste_style(project, [target_id], source)
    macro.description = f"Style like {source.label or noun(source)}"
    return macro


def paste_style(project: Project, target_ids: list[str], source: Any) -> Macro:
    """Give each plot in `target_ids` the look of `source`, one undo step.

    `source` may be a copy taken earlier: the style that was copied is pasted,
    whatever has happened to the plot since.
    """
    steps = []
    for target_id in target_ids:
        target, _ = _locate(project, target_id, "artists")
        trial = target.model_copy()
        for name in STYLE:
            if name not in type(target).model_fields or not hasattr(source, name):
                continue
            value = getattr(source, name)
            if value == getattr(target, name):
                continue
            try:
                setattr(trial, name, value)
            except ValueError:
                continue
            steps.append(SetField(target_id, (name,), value))
    many = f" to {len(target_ids)} plots" if len(target_ids) > 1 else ""
    return Macro(f"Paste style{many}", steps)


def drawing_order(project: Project, artist_id: str) -> list:
    """The plots of the panel holding `artist_id`, in the order they are
    drawn: by z-order, and as Matplotlib does on a tie, as they were added."""
    _, axes = _locate(project, artist_id, "artists")
    return sorted(axes.artists, key=lambda a: a.zorder)


def to_front(project: Project, artist_id: str, front: bool) -> SetField | None:
    """Draw the plot above (`front`) or below every other plot of its panel;
    None when there is no other."""
    others = [a.zorder for a in drawing_order(project, artist_id) if a.id != artist_id]
    if not others:
        return None
    zorder = max(others) + 1 if front else min(others) - 1
    text = "Bring to front" if front else "Send to back"
    return SetField(artist_id, ("zorder",), float(zorder), text)


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
    copy.id = new_id()
    _renew_ids(copy.axes)
    name = project.figures[index].name
    first = f"{name} (copy)"
    copy.name = (
        first
        if not any(f.name == first for f in project.figures)
        else _free_name(project, f"{name} (copy {{}})", 2)
    )
    step = InsertItem(None, "figures", copy, index + 1)
    return Macro(f"Duplicate {name}", [step]), copy


def _renew_ids(axes_list: list[Axes], loose: Sequence[Any] = ()) -> None:
    """Give copies of panels, and of plots taken from panels (`loose`), ids of
    their own, and point what refers to a copied object at its copy: an
    inset at its panel, a fit at its data, residuals at their fit. A reference
    to something that was not copied stays as it is."""
    plots = [*loose, *(artist for axes in axes_list for artist in axes.artists)]
    renamed = {obj.id: new_id() for obj in [*axes_list, *plots]}
    for axes in axes_list:
        axes.id = renamed[axes.id]
        if axes.inset is not None:
            axes.inset.parent = renamed.get(axes.inset.parent, axes.inset.parent)
    for plot in plots:
        plot.id = renamed[plot.id]
        if isinstance(plot, FitCurve | ResidualPlot):
            plot.target = renamed.get(plot.target, plot.target)


def duplicate_artists(project: Project, artist_ids: list[str]) -> tuple[Macro, list]:
    """Copies of the plots, each right after its original in the same panel
    (so drawn above it), as one undo step; and the copies.

    A copy with a label is labelled "… (copy)", so the legend tells them
    apart. A fit copied together with its data fits the copy of the data;
    copied alone, it fits the original. Residuals are made from a fit, not
    copied.
    """
    found = [_locate(project, oid, "artists") for oid in dict.fromkeys(artist_ids)]
    for artist, _ in found:
        if isinstance(artist, ResidualPlot):
            raise CommandError(
                "Residuals cannot be duplicated; add them again from the fit."
            )
    copies = [artist.model_copy(deep=True) for artist, _ in found]
    _renew_ids([], copies)
    for copy in copies:
        label = getattr(copy, "label", None)
        if label:
            copy.label = f"{label} (copy)"
    steps = []
    added: dict[str, int] = {}  # per panel: copies put in before this one
    for (artist, axes), copy in sorted(
        zip(found, copies, strict=True), key=lambda p: p[0][1].artists.index(p[0][0])
    ):
        index = axes.artists.index(artist) + 1 + added.get(axes.id, 0)
        added[axes.id] = added.get(axes.id, 0) + 1
        steps.append(InsertItem(axes.id, "artists", copy, index))
    text = noun(copies[0]) if len(copies) == 1 else f"{len(copies)} plots"
    return Macro(f"Duplicate {text}", steps), copies


def duplicate_axes(project: Project, axes_id: str) -> tuple[Macro, Axes]:
    """A copy of the panel with its plots and insets, in the cell to its
    right (a column is inserted if none is free), as one undo step."""
    axes, figure = _locate(project, axes_id, "axes")
    if axes.inset is not None:
        raise CommandError(
            "An inset cannot be duplicated; add another inset to its panel."
        )
    steps, place = _make_room(figure, axes, "right")
    insets = [a for a in figure.axes if a.inset and a.inset.parent == axes_id]
    copies = [axes.model_copy(deep=True), *(a.model_copy(deep=True) for a in insets)]
    _renew_ids(copies)
    copy = copies[0]
    copy.row, copy.rowspan, copy.col, copy.colspan = (
        place["row"],
        place["rowspan"],
        place["col"],
        1,
    )
    steps += [InsertItem(figure.id, "axes", each) for each in copies]
    return Macro("Duplicate panel", steps), copy


def same_range(
    project: Project, axes_id: str, field: str, limits: tuple[float, float]
) -> tuple[Macro, list[Axes]]:
    """Give the axis `field` ("x" or "y") of every panel of the figure the
    range `limits`, as one undo step; and the panels left out.

    Left out are insets, which have a range of their own, and a panel whose
    axis has another scale or another unit, where the same numbers would
    mean something else.
    """
    if field not in ("x", "y"):
        raise CommandError(f"the axis is x or y, not {field!r}")
    source, figure = _locate(project, axes_id, "axes")
    shown = getattr(source, field)
    steps = []
    skipped = []
    for axes in figure.axes:
        if axes.inset is not None:
            continue
        spec = getattr(axes, field)
        if axes is not source and (
            spec.scale != shown.scale
            or (spec.unit and shown.unit and spec.unit != shown.unit)
        ):
            skipped.append(axes)
            continue
        if spec.limits != limits:
            steps.append(SetField(axes.id, (field, "limits"), limits))
    return Macro(f"Same {field} range in all panels", steps), skipped


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
    steps, place = _make_room(figure, axes, side)
    new = Axes(**place)
    steps.append(InsertItem(figure.id, "axes", new))
    where = {"right": "to the right", "left": "to the left"}.get(side, side)
    return Macro(f"Add panel {where}", steps), new


def _make_room(figure: Figure, axes: Axes, side: Side) -> tuple[list, dict[str, int]]:
    """Steps that make a cell free beside `axes` (none if one is), and the
    grid position of that cell: row, rowspan, col, colspan of a panel put there."""
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
    return steps, place


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
