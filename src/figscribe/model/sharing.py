"""Which panels' axes are one axis, as the model says it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from figscribe.model.axes import AxisSpec
from figscribe.model.figure import Figure

if TYPE_CHECKING:
    from figscribe.model.project import Project


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


def typed_limits(figure: Figure, index: int, field: str) -> tuple[float, float] | None:
    """The range typed for the `field` axis of the panel `index`, there or on a
    panel that shares the axis, lowest end first; None while it is automatic."""
    typed = [
        spec.limits
        for i in sharing_group(figure, index, field)
        if (spec := getattr(figure.axes[i], field)) is not None and spec.limits
    ]
    if not typed:
        return None
    low, high = sorted(typed[-1])  # the range set last is the one the axis has
    return low, high


def x_limits_of(project: Project, artist_id: str) -> tuple[float, float] | None:
    """`typed_limits` of the x axis the artist `artist_id` is drawn on."""
    for figure in project.figures:
        for index, axes in enumerate(figure.axes):
            if any(artist.id == artist_id for artist in axes.artists):
                return typed_limits(figure, index, "x")
    return None
