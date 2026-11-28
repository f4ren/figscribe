"""How marked peaks look (decision 0083); the script writes the same."""

from __future__ import annotations

LABEL_OFFSET = 12
"""Points from a peak to its label."""
MARK_OFFSET = 7
"""Points from a peak to its triangle."""
LABEL_ROOM = 0.25
"""The y margin of an automatic range with labels, for those at its ends."""
MARK_ROOM = 0.12
"""The same for triangles."""


def peak_label(dips: bool) -> dict:
    """The options of `annotate` for a peak's x: above it, with a thin line to
    it; below a dip."""
    return {
        "xytext": (0, -LABEL_OFFSET if dips else LABEL_OFFSET),
        "textcoords": "offset points",
        "ha": "center",
        "va": "top" if dips else "bottom",
        "fontsize": "small",
        "arrowprops": {"arrowstyle": "-", "linewidth": 0.6, "shrinkB": 3},
    }


def peak_mark(dips: bool) -> dict:
    """The options of `plot` for the triangle at a peak."""
    return {
        "linestyle": "none",
        "marker": "^" if dips else "v",
        "markersize": 5,
        "color": "0.2",
        "label": "_nolegend_",
    }
