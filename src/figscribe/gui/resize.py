"""Resizing in the preview: an inset by dragging a corner, the panels of a
grid by dragging the gap between two columns or rows.

Geometry only, in Matplotlib's display coordinates (device pixels from the
bottom left), so that it can be tested without a window. The preview turns
a drag into one undo step on release.
"""

from __future__ import annotations

from dataclasses import dataclass

from matplotlib.transforms import Bbox

from figscribe.model import Figure

HANDLE = 6.0
"""Logical pixels around a corner or the middle of a gap that grab it."""
SMALLEST = 0.05
"""An inset keeps at least this fraction of its panel's width and height."""
NARROWEST = 0.1
"""A column or row keeps at least this share of the two being resized."""

CORNERS = {
    "lower left": (0, 0),
    "lower right": (1, 0),
    "upper left": (0, 1),
    "upper right": (1, 1),
}
"""Each corner of a box, as (x, y) of its edges: 0 the low, 1 the high."""


@dataclass
class Corner:
    """A corner of an inset, where a drag resizes it."""

    axes_id: str
    corner: str
    """A key of CORNERS."""
    at: tuple[float, float]
    """Where it is, in display coordinates."""


@dataclass
class Gap:
    """The gap between two columns (or rows) of the grid, where a drag moves
    the boundary between them."""

    field: str
    """"width_ratios" between columns, "height_ratios" between rows."""
    index: int
    """The column (row) before the gap; the next one is after it."""
    middle: float
    """Where the gap is: an x for columns, a y for rows."""
    extent: tuple[float, float]
    """Where along the gap it can be grabbed: the y range of the columns, or
    the x range of the rows."""
    span: tuple[float, float]
    """From the start of the column (row) before the gap to the end of the
    one after it: the room the two share. A row starts at its top."""


def corners(figure: Figure, boxes: dict[str, Bbox]) -> list[Corner]:
    """The corners of every inset drawn; `boxes` are the panels' boxes by id."""
    found = []
    for axes in figure.axes:
        box = boxes.get(axes.id)
        if axes.inset is None or box is None:
            continue
        for name, (i, j) in CORNERS.items():
            at = (box.x1 if i else box.x0, box.y1 if j else box.y0)
            found.append(Corner(axes.id, name, at))
    return found


def gaps(figure: Figure, boxes: dict[str, Bbox]) -> list[Gap]:
    """The gaps between neighbouring columns and rows of the grid."""
    grid = [a for a in figure.axes if a.inset is None and a.id in boxes]
    found = []
    for index in range(figure.layout.cols - 1):
        before = [boxes[a.id] for a in grid if a.col + a.colspan - 1 == index]
        after = [boxes[a.id] for a in grid if a.col == index + 1]
        if before and after:
            right = max(b.x1 for b in before)
            left = min(b.x0 for b in after)
            starts = [boxes[a.id].x0 for a in grid if a.col == index] or [right]
            ends = [boxes[a.id].x1 for a in grid if a.col + a.colspan - 1 == index + 1]
            boxes_here = before + after
            found.append(
                Gap(
                    "width_ratios",
                    index,
                    (right + left) / 2,
                    (min(b.y0 for b in boxes_here), max(b.y1 for b in boxes_here)),
                    (min(starts), max(ends or [left])),
                )
            )
    for index in range(figure.layout.rows - 1):
        above = [boxes[a.id] for a in grid if a.row + a.rowspan - 1 == index]
        below = [boxes[a.id] for a in grid if a.row == index + 1]
        if above and below:
            bottom = min(b.y0 for b in above)
            top = max(b.y1 for b in below)
            starts = [boxes[a.id].y1 for a in grid if a.row == index] or [bottom]
            ends = [boxes[a.id].y0 for a in grid if a.row + a.rowspan - 1 == index + 1]
            boxes_here = above + below
            found.append(
                Gap(
                    "height_ratios",
                    index,
                    (bottom + top) / 2,
                    (min(b.x0 for b in boxes_here), max(b.x1 for b in boxes_here)),
                    (max(starts), min(ends or [top])),
                )
            )
    return found


def grabbed(gap: Gap, x: float, y: float, reach: float) -> bool:
    """Whether (x, y) is on `gap`, within `reach` of its middle."""
    along, across = (y, x) if gap.field == "width_ratios" else (x, y)
    low, high = gap.extent
    return abs(across - gap.middle) <= reach and low <= along <= high


def bounds(parent: Bbox, inset: Bbox, corner: str, x: float, y: float):
    """The inset's bounds (left, bottom, width, height, as fractions of its
    panel) with `corner` moved to (x, y) and the opposite one where it was."""
    i, j = CORNERS[corner]
    fixed_x = inset.x0 if i else inset.x1
    fixed_y = inset.y0 if j else inset.y1
    low_x, high_x = sorted((fixed_x, x))
    low_y, high_y = sorted((fixed_y, y))
    left = (low_x - parent.x0) / parent.width
    bottom = (low_y - parent.y0) / parent.height
    width = max((high_x - low_x) / parent.width, SMALLEST)
    height = max((high_y - low_y) / parent.height, SMALLEST)
    return tuple(round(v, 3) for v in (left, bottom, width, height))


def ratios(current: list[float] | None, count: int, gap: Gap, at: float):
    """The ratios with the boundary of `gap` moved to `at` (an x for
    columns, a y for rows); the two sides keep their sum."""
    values = list(current) if current is not None else [1.0] * count
    start, end = gap.span
    share = (at - start) / (end - start) if end != start else 0.5
    share = min(max(share, NARROWEST), 1 - NARROWEST)
    both = values[gap.index] + values[gap.index + 1]
    values[gap.index] = round(both * share, 2)
    values[gap.index + 1] = round(both - values[gap.index], 2)
    return values
