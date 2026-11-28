"""Smoothing and normalising the values of a plot (decision 0083).

`plot_data` calls this for a plot that asks for it, so the renderer, the fits,
the dialogs and the code generator all get the same values. The script makes
the same calls; keep the two in step.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import savgol_filter

from figscribe.convert import PlotData, plot_data
from figscribe.fit.run import FitError, kept
from figscribe.io.errors import DataError
from figscribe.model.artists import Smoothing


class ProcessError(FitError, DataError):
    """What a plot asks to compute from its data cannot be: a fit cannot run on
    it, and the data cannot be drawn."""


def normaliser(plot, data) -> float:
    """What the plot's y values are divided by now; 1 if not normalised."""
    if plot.normalize is None:
        return 1.0
    shown = plot_data(
        plot.model_copy(update={"normalize": None, "reduction": None}), data
    )
    rows = measured(plot, shown)
    return divisor(plot.normalize, shown.x, shown.y, rows)


def processes(plot) -> bool:
    """Whether the plot's values are computed from its columns."""
    return any(
        getattr(plot, name, None) is not None for name in ("smoothing", "normalize")
    )


def measured(plot, shown: PlotData) -> np.ndarray:
    """The rows computed with: in the plot's range, not left out, x and y
    finite."""
    return (
        shown.used
        & kept(len(shown.x), plot.left_out)
        & np.isfinite(shown.x)
        & np.isfinite(shown.y)
    )


def processed(plot, shown: PlotData) -> PlotData:
    """`shown`, the plot's columns in the units it shows them in, with what the
    plot computes from them; every row of the file still."""
    rows = measured(plot, shown)
    y, yerr = shown.y, shown.yerr
    if plot.smoothing is not None:
        y = smoothed(plot.smoothing, y, rows)
    if plot.normalize is not None:
        by = divisor(plot.normalize, shown.x, y, rows)
        y = y / by
        yerr = None if yerr is None else yerr / by
    return replace(shown, y=y, yerr=yerr)


def divisor(how: str, x: np.ndarray, y: np.ndarray, rows: np.ndarray) -> float:
    """What normalised values are divided by: the largest of `rows`, or the
    area under them, by trapezoids with x in order."""
    what = "maximum" if how == "max" else "area"
    by = np.nan
    if rows.any() and how == "max":
        by = float(np.max(y[rows]))
    elif rows.any():
        order = np.argsort(x[rows], kind="stable")
        by = float(np.trapezoid(y[rows][order], x[rows][order]))
    if not by > 0:
        raise ProcessError(f"normalising needs a {what} above zero")
    return by


def smoothed(how: Smoothing, y: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """`y` with the values of `rows` smoothed over each other, in their order;
    the other rows keep theirs."""
    count = int(rows.sum())
    if how.window > count:
        raise ProcessError(
            f"smoothing over {how.window} points needs at least as many; the plot "
            f"has {count}"
        )
    values = np.asarray(y, dtype=float).copy()
    if how.method == "savgol":
        values[rows] = savgol_filter(values[rows], how.window, how.order)
    else:
        values[rows] = uniform_filter1d(values[rows], how.window, mode="nearest")
    return values
