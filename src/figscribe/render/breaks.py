"""Drawing a broken axis, for the renderer and the code generator.

The axis stays one Matplotlib axis with a scale of its own, which gives each
break a narrow strip and leaves the rest linear; what falls into the strip is
clipped away, and the break marks are drawn at its ends. So plots, fits, notes,
the legend, shared panels and the right y axis work as on any axis. The script
defines the same two functions this module uses.
"""

from __future__ import annotations

import math

import matplotlib
import numpy as np
from matplotlib.path import Path
from matplotlib.ticker import MaxNLocator

from figscribe.model.breaks import Breaks

GAP = 0.025
"""The part of the axis length each break takes."""
NICE = [1, 2, 2.5, 5, 10]
"""The tick steps Matplotlib's AutoLocator chooses from."""
MARK_SIZE = 7.0
"""Length of a break mark in pt."""


def overlapping(breaks: Breaks, low: float, high: float) -> Breaks:
    """The breaks that cut into the range from `low` to `high`, in either order."""
    low, high = sorted((low, high))
    return [(start, end) for start, end in breaks if start < high and end > low]


def pieces(breaks: Breaks, low: float, high: float) -> Breaks:
    """The stretches of low..high that the breaks leave."""
    low, high = sorted((low, high))
    left = []
    at = low
    for start, end in overlapping(breaks, low, high):
        if start > at:
            left.append((at, start))
        at = max(at, end)
    if high > at:
        left.append((at, high))
    return left


def gap_width(breaks: Breaks, low: float, high: float) -> float:
    """How much of the axis, in the data's unit, each break takes so that it is
    GAP of the axis long; 0 if the breaks leave nothing of the range. Rounded,
    as the script writes it."""
    visible = sum(end - start for start, end in pieces(breaks, low, high))
    share = min(GAP, 0.5 / max(len(breaks), 1))
    return float(f"{share * visible / (1 - len(breaks) * share):.4g}")


def squeezed(breaks: Breaks, width: float):
    """The two functions of a "function" scale that is linear except that each
    break takes only `width` of the axis."""

    def forward(values):
        values = np.asarray(values, dtype=float)
        shown = values.copy()
        for start, end in breaks:
            part = np.clip((values - start) / (end - start), 0, 1)
            shown = shown - part * (end - start - width)
        return shown

    def inverse(shown):
        shown = np.asarray(shown, dtype=float)
        values = shown.copy()
        removed = 0.0
        for start, end in breaks:
            part = np.clip((shown - (start - removed)) / width, 0, 1)
            values = values + part * (end - start - width)
            removed += end - start - width
        return values

    return forward, inverse


def crossings(x, y, x_breaks: Breaks, y_breaks: Breaks) -> np.ndarray:
    """Where the line from one point to the next would cross a break: the
    positions at which np.insert puts a NaN so that none is drawn there."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    crossing = np.zeros(max(x.size - 1, 0), dtype=bool)
    for values, breaks in ((x, x_breaks), (y, y_breaks)):
        low = np.minimum(values[:-1], values[1:])
        high = np.maximum(values[:-1], values[1:])
        for start, end in breaks:
            crossing |= (high > start) & (low < end)
    return np.flatnonzero(crossing) + 1


def curve_parts(
    low: float, high: float, breaks: Breaks, count: int
) -> list[tuple[float, float, int]]:
    """(start, end, number of points) to sample a curve with, from `low` to
    `high`, on each stretch the breaks leave, by its length."""
    stretches = pieces(breaks, low, high)
    total = sum(end - start for start, end in stretches)
    return [
        (start, end, max(2, round(count * (end - start) / total)))
        for start, end in stretches
    ]


# --- ticks ------------------------------------------------------------------


def break_ticks(
    breaks: Breaks,
    low: float,
    high: float,
    space: int,
    *,
    ticks: list[float] | None = None,
    labels: list[str] | None = None,
    step: float | None = None,
    parts: int | None = None,
    minor: bool = True,
    clear: float = 0.0,
) -> tuple[list[float], list[str] | None, list[float]]:
    """The major ticks, their typed labels and the minor ticks of a broken
    axis showing low..high, none of them within a break.

    `ticks` and `labels` as typed, `step` the distance of the major ticks,
    `parts` how many parts the minor ones divide it into; `space` how many
    numbers fit along the whole axis. Automatic ticks stay `clear` of the break
    marks, where a stretch has others.
    """
    stretches = pieces(breaks, low, high)
    if not stretches:
        return [], None if labels is None else [], []
    if ticks is not None:
        kept = [i for i, t in enumerate(ticks) if _within(t, stretches)]
        major = [float(ticks[i]) for i in kept]
        named = None if labels is None else [labels[i] for i in kept]
        spacing = abs(ticks[1] - ticks[0]) if len(ticks) > 1 else None
    elif step is not None:
        major = [t for stretch in stretches for t in _multiples(step, *stretch)]
        named, spacing = None, step
    else:
        major, spacing = _chosen(stretches, space, breaks, clear)
        named = None
    if not minor or spacing is None:
        return major, named, []
    if parts is None:  # as AutoMinorLocator does
        mantissa = 10 ** (math.log10(spacing) % 1)
        parts = 5 if any(math.isclose(mantissa, n) for n in NICE if n != 2) else 4
    small = spacing / parts
    between = [
        t
        for stretch in stretches
        for t in _multiples(small, *stretch)
        if not any(abs(t - m) < small / 2 for m in major)
    ]
    return major, named, between


def _chosen(
    stretches: Breaks, space: int, breaks: Breaks, clear: float
) -> tuple[list[float], float]:
    """Ticks Matplotlib's way, one step for all stretches; a stretch that step
    misses gets the roundest number near its middle."""
    total = sum(end - start for start, end in stretches)
    locator = MaxNLocator(nbins=max(space, 2), steps=NICE)
    spacing = float(np.diff(locator.tick_values(0, total))[0])
    major = []
    marks = [end for stretch in breaks for end in stretch]
    for start, end in stretches:
        found = _multiples(spacing, start, end)
        away = [t for t in found if all(abs(t - m) > clear for m in marks)]
        found = away or found
        finer = spacing
        while not found:
            finer /= 10
            for factor in (5, 2, 1):
                if inside := _multiples(finer * factor, start, end):
                    middle = (start + end) / 2
                    found = [min(inside, key=lambda t: abs(t - middle))]
                    break
        major += found
    return major, spacing


def _multiples(step: float, low: float, high: float) -> list[float]:
    """The whole multiples of `step` within low..high, without the noise of
    floating point: 0.3, not 0.30000000000000004."""
    first = math.ceil(low / step - 1e-9)
    last = math.floor(high / step + 1e-9)
    return [float(f"{i * step:.12g}") + 0 for i in range(first, last + 1)]


def _within(value: float, stretches: Breaks) -> bool:
    return any(start <= value <= end for start, end in stretches)


# --- drawing ----------------------------------------------------------------


def cut_out(ax, x_breaks: Breaks, y_breaks: Breaks, twin=None, frame=True) -> None:
    """Leave the breaks of `ax` blank: its plots, grid lines and frame are
    clipped there, and slanted marks stand at their ends. `twin` is its right
    y axis; without `frame` there are no lines on the top and right."""
    xs, ys = ax.get_xlim(), ax.get_ylim()
    shown = _clip(x_breaks, y_breaks, xs, ys)
    for artist in [*ax.lines, *ax.collections, *ax.patches]:
        artist.set_clip_path(shown, ax.transData)
    for line in [*ax.get_xgridlines(), *ax.get_ygridlines()]:
        line.set_clip_path(shown, ax.transData)
    axes = [ax] if twin is None else [ax, twin]
    for spine in [s for each in axes for s in each.spines.values()]:
        spine.set_clip_path(shown, ax.transData)
        spine.set_clip_on(True)
    if twin is not None:
        # Its y values are its own: only the x breaks cut it.
        along = _clip(x_breaks, [], xs, (0.0, 1.0))
        transform = ax.get_xaxis_transform()
        for artist in [*twin.lines, *twin.collections, *twin.patches]:
            artist.set_clip_path(along, transform)
        twin.spines["right"].set_clip_path(along, transform)
    style = {
        "linestyle": "none",
        "color": matplotlib.rcParams["axes.edgecolor"],
        "markeredgewidth": matplotlib.rcParams["axes.linewidth"],
        "markersize": MARK_SIZE,
        "clip_on": False,
        "scalex": False,
        "scaley": False,
    }
    ends = _ends(x_breaks, xs)
    if ends:
        sides = [0, 1] if frame else [0]
        ax.plot(
            [e for _ in sides for e in ends],
            [side for side in sides for _ in ends],
            marker=[(-0.5, -1), (0.5, 1)],
            transform=ax.get_xaxis_transform(),
            **style,
        )
    ends = _ends(y_breaks, ys)
    if ends:
        sides = [0, 1] if frame and twin is None else [0]
        ax.plot(
            [side for side in sides for _ in ends],
            [e for _ in sides for e in ends],
            marker=[(-1, -0.5), (1, 0.5)],
            transform=ax.get_yaxis_transform(),
            **style,
        )


def _clip(x_breaks: Breaks, y_breaks: Breaks, xs, ys) -> Path:
    """What stays visible, as rectangles in data coordinates, reaching well
    past the edges of the axes so that only the breaks cut."""

    def stretches(breaks, limits):
        low, high = sorted(limits)
        room = high - low
        return pieces(breaks, low - room, high + room)

    return Path.make_compound_path(
        *(
            Path([(a, c), (b, c), (b, d), (a, d), (a, c)], closed=True)
            for a, b in stretches(x_breaks, xs)
            for c, d in stretches(y_breaks, ys)
        )
    )


def _ends(breaks: Breaks, limits) -> list[float]:
    low, high = sorted(limits)
    return [e for stretch in breaks for e in stretch if low < e < high]
