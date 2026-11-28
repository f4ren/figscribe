"""Baseline, smoothing and normalising the values of a plot (decision 0083).

`plot_data` calls this for a plot that asks for it, so the renderer, the fits,
the dialogs and the code generator all get the same values. The script makes
the same calls; keep the two in step.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks, savgol_filter

from figscribe.convert import PlotData, plot_data, within
from figscribe.fit.run import FitError, kept
from figscribe.io.errors import DataError
from figscribe.model.artists import Baseline, FitCurve, ResidualPlot, Smoothing
from figscribe.model.figure import Figure


class ProcessError(FitError, DataError):
    """What a plot asks to compute from its data cannot be: a fit cannot run on
    it, and the data cannot be drawn."""


def cannot_compute(plot, data) -> str | None:
    """Why what the plot asks to compute cannot be, such as after a new version
    of its file; None if it can, or if something else keeps it from being read,
    which is told elsewhere."""
    if not processes(plot):
        return None
    try:
        plot_data(plot, data)
    except ProcessError as exc:
        return str(exc)
    except (DataError, ValueError, KeyError, IndexError):
        return None
    return None


def not_computable(figure: Figure, data) -> dict[str, str]:
    """{artist id: why} of the plots of the figure that are not drawn because
    their values cannot be computed, and of their fits and residuals. The
    renderer and the code generator leave them out alike."""
    artists = [a for axes in figure.axes for a in axes.artists]
    found = {a.id: why for a in artists if (why := cannot_compute(a, data))}
    for kind, what in ((FitCurve, "the plot it fits"), (ResidualPlot, "its fit")):
        for artist in artists:
            if isinstance(artist, kind) and artist.target in found:
                found[artist.id] = f"{what} cannot be computed"
    return found


def processes(plot) -> bool:
    """Whether the plot's values are computed from its columns."""
    return any(
        getattr(plot, name, None) is not None
        for name in ("baseline", "smoothing", "normalize")
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
    if plot.baseline is not None:
        y = y - baseline_curve(plot.baseline, shown.x, y, rows)
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


def peak_rows(plot, shown: PlotData) -> np.ndarray:
    """The points of `shown` that are searched for peaks."""
    rows = np.isfinite(shown.x) & np.isfinite(shown.y)
    if not shown.reduced:  # fewer points have the rows taken out already
        rows &= shown.used & kept(len(shown.x), plot.left_out)
    return rows


def outside_breaks(
    places: np.ndarray, shown: PlotData, x_breaks, y_breaks
) -> np.ndarray:
    """The places not within a break of the axes the plot is drawn against."""
    for values, ends in ((shown.x, x_breaks), (shown.y, y_breaks)):
        for a, b in ends:
            at = values[places]
            places = places[~((at > a) & (at < b))]
    return places


def peaks_of(plot, shown: PlotData) -> np.ndarray:
    """The places, in `shown`, of the peaks the plot marks: of the points it
    draws that are measured and not left out."""
    how = plot.peaks
    rows = peak_rows(plot, shown)
    places = np.flatnonzero(rows)
    values = -shown.y[rows] if how.dips else shown.y[rows]
    if values.size < 3:
        return places[:0]
    prominence = how.prominence or PROMINENCE * np.ptp(values)
    found, _ = find_peaks(values, prominence=prominence, distance=how.distance)
    return places[found]


PROMINENCE = 0.1
"""Of the span of the values: how far a peak stands out unless it is said."""


def peak_text(value: float, decimals: int | None, comma: bool) -> str:
    """The x of a peak as it is written beside it."""
    text = f"{value:.4g}" if decimals is None else f"{value:.{decimals}f}"
    return text.replace(".", ",") if comma else text


def degree_of(how: Baseline) -> int:
    return {"constant": 0, "linear": 1}.get(how.shape, how.degree)


def baseline_curve(
    how: Baseline, x: np.ndarray, y: np.ndarray, rows: np.ndarray
) -> np.ndarray:
    """The baseline at every x: a polynomial fitted by least squares to the
    values of `rows` within its ranges, all of them without ranges."""
    base = rows
    if how.ranges:
        base = rows & np.logical_or.reduce([within(x, ends) for ends in how.ranges])
    degree = degree_of(how)
    if np.unique(x[base]).size < degree + 1:
        where = "its ranges hold" if how.ranges else "the plot has"
        count = int(base.sum())
        raise ProcessError(
            f"the baseline needs at least {degree + 1} points at different x to "
            f"fit; {where} {count}"
        )
    return np.polynomial.Polynomial.fit(x[base], y[base], degree)(x)


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
