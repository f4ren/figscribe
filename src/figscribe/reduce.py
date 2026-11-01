"""Fewer points drawn: groups of rows averaged or thinned (decision 0045).

`plot_data` calls this for a plot with a reduction, so the renderer, the
fits, the dialogs and the code generator all get the same points. The script
makes the same calls to `binned_statistic`, so that they agree bit for bit;
keep the two in step.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import binned_statistic

from figscribe.convert import PlotData
from figscribe.model.artists import Reduction


def reduced(plot, shown: PlotData) -> PlotData:
    """The points of `plot` after its reduction, from `shown`, its columns as
    the plot shows them, every row of the file.

    The order is the unit conversion and the x range (both in `shown`), the rows
    left out (removed, or replaced), the rows with a value that is not finite,
    then the groups. A group is a run of rows of the file, whatever has been
    taken out of it."""
    from figscribe.fit.run import kept

    how: Reduction = plot.reduction
    x, y, xerr, yerr = shown.x, shown.y, shown.xerr, shown.yerr
    total = len(x)
    rows = np.arange(total)
    left_out = ~kept(total, plot.left_out)
    inside = shown.used
    finite = np.isfinite(x) & np.isfinite(y)
    for errors in (xerr, yerr):
        if errors is not None:
            finite &= np.isfinite(errors)
    measured = inside & finite & ~left_out

    filled = y
    replaced = np.zeros(total, dtype=bool)
    if how.replace_left_out and measured.any():
        replaced = inside & left_out & np.isfinite(x)
        good = np.flatnonzero(measured)
        filled = y.copy()
        for row in np.flatnonzero(replaced):
            # The nearest measured rows before and after; at an end, the one.
            at = np.searchsorted(good, row)
            near = y[good[[max(at - 1, 0), min(at, good.size - 1)]]]
            filled[row] = near.mean()
    member = measured | replaced
    if how.method in ("mean", "median") and not how.keep_last and total % how.count:
        member &= rows < total // how.count * how.count
        measured &= member

    if how.method == "every":
        chosen = member & (rows % how.count == 0)
        return _points(
            x[chosen],
            filled[chosen],
            _own(xerr, chosen, measured),
            _own(yerr, chosen, measured),
            rows[chosen],
        )
    if not member.any():
        return _points(*(np.empty(0) for _ in range(2)), None, None, rows[:0])

    if how.method == "interval":
        start = x[inside & finite].min()
        group = ((x[member] - start) // how.width).astype(int)
    else:
        group = rows[member] // how.count
    _, group = np.unique(group, return_inverse=True)
    bins = np.arange(group.max() + 2)

    def stat(values, kind, among=group):
        return binned_statistic(among, values, kind, bins=bins).statistic

    mean_y = stat(filled[member], "median" if how.method == "median" else "mean")
    points = (stat(x[member], "mean"), mean_y)
    first = stat(rows[member], "min").astype(int)
    if how.method == "median":
        return _points(*points, None, None, first)

    # The errors count the measured rows only.
    among = group[measured[member]]
    count = stat(y[measured], "count", among)
    spread = np.maximum(count - 1, 1)

    def propagated(errors):
        return np.sqrt(stat(errors[measured] ** 2, "sum", among)) / np.maximum(count, 1)

    new_yerr = (
        propagated(yerr)
        if yerr is not None
        else stat(y[measured], "std", among) / np.sqrt(spread)
    )
    new_xerr = None if xerr is None else propagated(xerr)
    # No error rather than an error of 0, which no fit can weight by.
    for errors in (new_xerr, new_yerr):
        if errors is not None:
            errors[errors == 0] = np.nan
    return _points(*points, new_xerr, new_yerr, first)


def _own(errors, chosen, measured):
    """The errors of the rows taken as they are; none for a replaced row."""
    if errors is None:
        return None
    return np.where(measured[chosen], errors[chosen], np.nan)


def _points(x, y, xerr, yerr, rows) -> PlotData:
    return PlotData(
        x=x,
        y=y,
        xerr=xerr,
        yerr=yerr,
        used=np.ones(len(x), dtype=bool),
        reduced=True,
        rows=rows,
    )
