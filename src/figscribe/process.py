"""Smoothing the values of a plot (decision 0083).

`plot_data` calls this for a plot that asks for it, so the renderer, the fits,
the dialogs and the code generator all get the same values. The script makes
the same calls; keep the two in step.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import savgol_filter

from figscribe.convert import PlotData
from figscribe.fit.run import FitError, kept
from figscribe.io.errors import DataError
from figscribe.model.artists import Smoothing


class ProcessError(FitError, DataError):
    """What a plot asks to compute from its data cannot be: a fit cannot run on
    it, and the data cannot be drawn."""


def processes(plot) -> bool:
    """Whether the plot's values are computed from its columns."""
    return getattr(plot, "smoothing", None) is not None


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
    return replace(shown, y=smoothed(plot.smoothing, shown.y, rows))


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
