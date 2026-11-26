"""Which panels' axes are one axis, as the model says it."""

from __future__ import annotations

from figscribe.model.axes import AxisSpec
from figscribe.model.figure import Figure


def share_partner(figure: Figure, index: int, axis: str) -> int | None:
    """Index of the axes that axes `index` shares `axis` ("x" or "y") with.

    The first axes, or the first in the same column (x, "col") or row (y,
    "row"), counted by where an axes starts; None when nothing is shared or
    the axes is the first of its group.
    """
    mode = figure.layout.share_x if axis == "x" else figure.layout.share_y
    me = figure.axes[index]
    if mode == "none" or me.inset is not None:
        return None
    along = "col" if axis == "x" else "row"
    for i, other in enumerate(figure.axes[:index]):
        if other.inset is not None:
            continue
        if mode == "all" or getattr(other, along) == getattr(me, along):
            return i
    return None


def sharing_group(figure: Figure, index: int, field: str) -> list[int]:
    """The indices of the axes whose `field` axis is one with that of axes
    `index`, its own included, in order. A right y axis shares with none."""
    if field == "y_right" or figure.axes[index].inset is not None:
        return [index]

    def first(i: int) -> int:
        partner = share_partner(figure, i, field)
        return i if partner is None else partner

    return [
        i
        for i, axes in enumerate(figure.axes)
        if i == index or (axes.inset is None and first(i) == first(index))
    ]


def sharing_specs(figure: Figure, index: int, field: str) -> list[AxisSpec]:
    """The settings of the other panels' axes that are one with the `field`
    axis of the axes `index`. They have one set of ticks and numbers between
    them."""
    return [
        getattr(figure.axes[i], field)
        for i in sharing_group(figure, index, field)
        if i != index
    ]
