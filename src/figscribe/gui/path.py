"""Where an object is in the figure, as a path: Figure › Panel A › X axis.

The property panel shows it above the settings; every part but the last
leads to the object it names.
"""

from __future__ import annotations

from figscribe.commands import CommandError, find
from figscribe.gui.axisform import AXIS_TITLES
from figscribe.gui.document import Document, split_axis
from figscribe.gui.names import KIND_NAMES, panel_name
from figscribe.model import Axes, Figure

Part = tuple[str, str | None]
"""A part of the path: its text, and the id of what it leads to (None for the
last part, which is where the user already is)."""


def path_to(document: Document, oid: str) -> list[Part]:
    """The path to the object or axis `oid`; empty if it is not in the project."""
    axis = split_axis(oid)
    if axis is not None:
        host = _panel(document, axis[0])
        if host is None:
            return []
        *above, (text, _) = host
        return [*above, (text, axis[0]), (AXIS_TITLES[axis[1]].capitalize(), None)]
    if any(source.id == oid for source in document.project.sources):
        return [("Data file", None)]
    try:
        obj = find(document.project, oid)
    except CommandError:
        return []
    if isinstance(obj, Figure):
        return [("Figure", None)]
    if isinstance(obj, Axes):
        return _panel(document, oid) or []
    for figure in document.project.figures:
        for axes in figure.axes:
            if obj in axes.artists:
                above = _panel(document, axes.id)
                *rest, (text, _) = above
                kind = KIND_NAMES.get(obj.kind, type(obj).__name__)
                return [*rest, (text, axes.id), (kind, None)]
    return []


def _panel(document: Document, axes_id: str) -> list[Part] | None:
    """The path to a panel, whose last part still names it, without a target:
    the caller says whether it is the end of the path or on the way."""
    for figure in document.project.figures:
        for axes in figure.axes:
            if axes.id != axes_id:
                continue
            head = [(figure.name, figure.id)]
            if axes.inset is None:
                return [*head, (_short(figure, axes), None)]
            host = next((a for a in figure.axes if a.id == axes.inset.parent), None)
            if host is None:
                return [*head, ("Inset", None)]
            return [*head, (_short(figure, host), host.id), ("Inset", None)]
    return None


def _short(figure: Figure, axes: Axes) -> str:
    """ "Panel A", without the position or title that `panel_name` adds."""
    return panel_name(figure, axes).split(" · ")[0]
