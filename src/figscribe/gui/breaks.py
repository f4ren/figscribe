"""Proposing where to break an axis, for the axis form and the preview's menu."""

from __future__ import annotations

import numpy as np

from figscribe.gui.dates import axis_on_dates
from figscribe.gui.document import Document
from figscribe.model.breaks import breaks_blocked, own_breaks
from figscribe.model.validate import axis_values as drawn_values
from figscribe.render.breaks import widest_gap
from figscribe.render.ticks import PREFIXES

WORTH = 0.2
"""The share of the data's span an empty stretch must have to be offered."""


def panel_index(document: Document, axes_id: str) -> int | None:
    figure = document.figure
    if figure is None:
        return None
    return next((i for i, a in enumerate(figure.axes) if a.id == axes_id), None)


def current_breaks(document: Document, axes_id: str, field: str) -> list:
    """The breaks of the axis, set on it or on a panel sharing it."""
    index = panel_index(document, axes_id)
    if index is None or field == "y_right":
        return []
    found = own_breaks(document.figure, index, field)
    return found[0] if found else []


def axis_values(document: Document, axes_id: str, field: str) -> np.ndarray:
    """What is drawn against the axis, in data units."""
    index = panel_index(document, axes_id)
    if index is None:
        return np.array([])
    return drawn_values(document.figure, index, field, document.data)


def break_entries(
    document: Document,
    axes_id: str,
    fields: tuple[str, ...] = ("x", "y"),
    spot: tuple[float, float] | None = None,
) -> list[tuple[str, str, list]]:
    """(menu text, field, breaks) for what a menu offers to do with the breaks
    of a panel: cut an empty stretch of the data out of an axis, the one at
    `spot`, (x, y), if it is in one, or take the axis's breaks out."""
    index = panel_index(document, axes_id)
    if index is None:
        return []
    entries = []
    for field in fields:
        breaks = current_breaks(document, axes_id, field)
        dated = axis_on_dates(document.project, axes_id, field)
        if not dated and breaks_blocked(document.figure, index, field) is None:
            at = None if spot is None else float(spot["xy".index(field)])
            found = proposed_break(document, axes_id, field, at)
            if found is not None:
                prefix = getattr(document.figure.axes[index], field).prefix
                factor = 10.0 ** PREFIXES[prefix] if prefix else 1.0
                start, end = (f"{end / factor:.6g}" for end in found)  # as shown
                text = f"Break the {field} axis (cut out {start} to {end})"
                entries.append((text, field, sorted([*breaks, found])))
        if breaks:
            entries.append((f"Remove the breaks of the {field} axis", field, []))
    return entries


def proposed_break(
    document: Document, axes_id: str, field: str, at: float | None = None
) -> tuple[float, float] | None:
    """An empty stretch of the data worth cutting out, the one at `at` if there
    is one there; None if the data has none."""
    values = axis_values(document, axes_id, field)
    values = values[np.isfinite(values)]
    if values.size < 2:
        return None
    breaks = current_breaks(document, axes_id, field)
    span = float(values.max() - values.min())
    for place in [at, None] if at is not None else [None]:
        found = widest_gap(values, breaks, place)
        if found is not None and found[1] - found[0] >= WORTH * span:
            return found
    return None
