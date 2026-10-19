"""Panel sharing rules, shared by the renderer and the code generator.

Both decide from the model, not from Matplotlib objects, so that the script
the generator writes makes exactly the calls the renderer makes.
"""

from __future__ import annotations

from figscribe.model import Axes, Figure


def share_partner(figure: Figure, index: int, axis: str) -> int | None:
    """Index of the axes that axes `index` shares `axis` ("x" or "y") with.

    The first axes, or the first in the same column (x, "col") or row (y,
    "row"), counted by where an axes starts; None when nothing is shared or
    the axes is the first of its group.
    """
    mode = figure.layout.share_x if axis == "x" else figure.layout.share_y
    if mode == "none":
        return None
    along = "col" if axis == "x" else "row"
    me = figure.axes[index]
    for i, other in enumerate(figure.axes[:index]):
        if mode == "all" or getattr(other, along) == getattr(me, along):
            return i
    return None


def hidden_tick_labels(figure: Figure) -> list[tuple[bool, bool]]:
    """Per axes: whether its x and its y tick labels are hidden.

    Hidden when a sharing partner already shows them: x labels when a partner
    lies below with exactly the same columns, y labels when one lies to the
    left with exactly the same rows.

    Not plt.subplots' rule of "only the bottom row and left column": in a grid
    with gaps or spans, that strips labels from an axes with no partner below,
    and its column ends up with no x tick labels at all. Same extent, not mere
    overlap: a partner of another width spreads the shared limits over another
    length, so its ticks do not line up and cannot stand in for these.
    """
    groups = {axis: _groups(figure, axis) for axis in ("x", "y")}
    hidden = []
    for i, axes in enumerate(figure.axes):
        below = any(
            other.row >= axes.row + axes.rowspan
            and (other.col, other.colspan) == (axes.col, axes.colspan)
            for other in groups["x"][i]
        )
        left = any(
            other.col + other.colspan <= axes.col
            and (other.row, other.rowspan) == (axes.row, axes.rowspan)
            for other in groups["y"][i]
        )
        hidden.append((below, left))
    return hidden


def _groups(figure: Figure, axis: str) -> list[list[Axes]]:
    """For every axes, the other axes it shares `axis` with."""
    roots = []
    for i in range(len(figure.axes)):
        root, partner = i, share_partner(figure, i, axis)
        while partner is not None:
            root, partner = partner, share_partner(figure, partner, axis)
        roots.append(root)
    return [
        [figure.axes[j] for j in range(len(roots)) if roots[j] == roots[i] and j != i]
        for i in range(len(roots))
    ]
