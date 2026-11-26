"""Broken axes: which axis may be broken, and which breaks it is drawn with.

A break cuts a stretch out of an axis. Panels that share an axis share its
breaks. The renderer, the code generator, the panel and the problem list all
ask here.
"""

from __future__ import annotations

from figscribe.model.artists import ImagePlot
from figscribe.model.figure import Figure
from figscribe.model.sharing import sharing_group, typed_limits

Breaks = list[tuple[float, float]]


def breaks_blocked(figure: Figure, index: int, field: str) -> str | None:
    """Why the `field` axis ("x", "y" or "y_right") of the panel `index` cannot
    be broken; None if it can."""
    if field == "y_right":
        return "the right y axis cannot be broken, only the x and the left y axis"
    group = [figure.axes[i] for i in sharing_group(figure, index, field)]
    if any(getattr(axes, field).scale != "linear" for axes in group):
        return "only a linear axis can be broken"
    if any(isinstance(a, ImagePlot) for axes in group for a in axes.artists):
        return "an image cannot be drawn on a broken axis (a color mesh can)"
    return None


def own_breaks(figure: Figure, index: int, field: str) -> list[Breaks]:
    """The breaks set on the panels that share the axis, those that have any."""
    if getattr(figure.axes[index], field) is None:
        return []
    return [
        list(spec.breaks)
        for i in sharing_group(figure, index, field)
        if (spec := getattr(figure.axes[i], field)) is not None and spec.breaks
    ]


def effective_breaks(figure: Figure, index: int, field: str) -> Breaks:
    """The breaks the axis is drawn with: those of the first panel sharing it
    that has any, and none where it cannot be broken."""
    found = own_breaks(figure, index, field)
    if not found or breaks_blocked(figure, index, field) is not None:
        return []
    return found[0]


def line_breaks(figure: Figure, index: int, field: str) -> Breaks:
    """The breaks no line may run across. Of the effective ones, a break that a
    typed range does not show, because it lies outside the range or around all
    of it, is not drawn, and the lines stay whole there."""
    breaks = effective_breaks(figure, index, field)
    if not breaks:
        return []
    typed = typed_limits(figure, index, field)
    if typed is None:
        return breaks  # a line cannot cross a break that the data do not reach
    low, high = typed
    return [
        (start, end)
        for start, end in breaks
        if start < high and end > low and not (start <= low and high <= end)
    ]
