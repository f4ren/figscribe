"""Reference lines and shaded ranges, placed where the user points.

Shared by the Insert menu and the outline, which place one in the middle of
what a panel shows, and the preview, which places one where it was clicked.
"""

from __future__ import annotations

import math
from typing import Literal

from figscribe.commands import InsertItem, Macro
from figscribe.model import ReferenceLine, ShadedSpan

Kind = Literal["refline", "span"]
Orientation = Literal["vertical", "horizontal"]

ENTRIES: list[tuple[str, Kind, Orientation]] = [
    ("Vertical line", "refline", "vertical"),
    ("Horizontal line", "refline", "horizontal"),
    ("Shaded x range", "span", "vertical"),
    ("Shaded y range", "span", "horizontal"),
]
"""What the menus offer, in their order."""

UNDO_TEXTS = {
    ("refline", "vertical"): "Add a vertical line",
    ("refline", "horizontal"): "Add a horizontal line",
    ("span", "vertical"): "Shade an x range",
    ("span", "horizontal"): "Shade a y range",
}

SPAN_PART = 5
"""A new range covers a fifth of what the axis shows."""
STEPS = 100
"""Values are rounded to a hundredth of what the axis shows, so that a
click gives 4.2 rather than 4.23718."""


def marking(
    kind: Kind,
    orientation: Orientation,
    low: float,
    high: float,
    *,
    log: bool = False,
    at: float | None = None,
) -> ReferenceLine | ShadedSpan:
    """A line at `at`, or a range around it, on an axis showing `low` to
    `high`; without `at`, in the middle. On a log axis the middle and the
    width are taken in decades."""
    forward, back = (math.log10, lambda v: 10.0**v) if log else (float, float)
    start, stop = forward(low), forward(high)
    centre = forward(at) if at is not None else (start + stop) / 2
    width = abs(stop - start)
    if kind == "refline":
        return ReferenceLine(
            orientation=orientation, at=_round(back(centre), width, log)
        )
    half = width / SPAN_PART / 2
    ends = [back(centre - half), back(centre + half)]
    rounded = [_round(v, width, log) for v in ends]
    if rounded[0] == rounded[1]:
        rounded = ends  # too narrow to round
    return ShadedSpan(orientation=orientation, start=rounded[0], end=rounded[1])


def _round(value: float, width: float, log: bool) -> float:
    """`value` rounded to what the axis can tell apart: two significant
    digits on a log axis, else a hundredth of the width it shows."""
    if value == 0 or not math.isfinite(value):
        return value
    if log:
        return float(f"{value:.2g}")
    if width <= 0:
        return value
    digits = -math.floor(math.log10(width / STEPS))
    return round(value, digits) + 0.0  # no -0.0


def add(axes_id: str, made: ReferenceLine | ShadedSpan) -> Macro:
    """The undo step that puts `made` into the panel `axes_id`."""
    text = UNDO_TEXTS[(made.kind, made.orientation)]
    return Macro(text, [InsertItem(axes_id, "artists", made)])
