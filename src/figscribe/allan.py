"""The Allan deviation of a time series, as figscribe draws it (decision 0036).

The code generator writes the same steps into the script with the same NumPy
expressions, so that both draw the same points; the pixel equivalence test
holds them together. The formulas are those of NIST SP 1065 for the
overlapping Allan deviation.
"""

from __future__ import annotations

import numpy as np

from figscribe.convert import scale, within
from figscribe.io.errors import DataError
from figscribe.model import AllanDeviationPlot, AxisSpec

SPACING_LIMIT = 62
"""Octaves tried for the averaging factors: 2**61, the last, is more points
than any series has, and 2**63 would not fit into an integer."""


def phase_of(values, data_type: str, tau0: float) -> np.ndarray:
    """The series as phase (time error) in s: fractional frequency values are
    summed up, starting from 0."""
    values = np.asarray(values, dtype=float)
    if data_type == "phase":
        return values
    return np.concatenate([[0.0], np.cumsum(values) * tau0])


def averaging_factors(count: int, taus: str) -> np.ndarray:
    """The factors m, τ = m·τ0, for `count` phase points: 1, 2, 4, … for
    "octave", 1, 2, 5, 10, … for "decade", every m for "all"; each up to
    (count − 1) // 2, the largest with two differences left."""
    top = (count - 1) // 2
    if taus == "all":
        return np.arange(1, top + 1)
    if taus == "octave":
        m = 2 ** np.arange(SPACING_LIMIT)
    else:
        m = np.array([k * 10**e for e in range(19) for k in (1, 2, 5)])
    return m[m <= top]


def overlapping_adev(phase: np.ndarray, tau0: float, m: np.ndarray) -> np.ndarray:
    """σ_y(τ) at τ = m·τ0 from phase data, overlapping estimator."""
    sigma = np.empty(m.size)
    for k, mk in enumerate(m):
        d = phase[2 * mk :] - 2 * phase[mk:-mk] + phase[: -2 * mk]
        sigma[k] = np.sqrt(np.sum(d**2) / (2 * (mk * tau0) ** 2 * d.size))
    return sigma


def sample_interval(times) -> float:
    """τ0 from a column of sample times: their median step. A DataError if
    the times are not evenly spaced (within 1 %), as the Allan deviation
    needs them."""
    steps = np.diff(np.asarray(times, dtype=float))
    tau0 = float(np.median(steps)) if steps.size else float("nan")
    if not tau0 > 0:
        raise DataError("the times do not increase, so they give no sample interval")
    worst = float(np.max(np.abs(steps - tau0)))
    if worst > 0.01 * tau0:
        raise DataError(
            f"the times are not evenly spaced: steps differ from {tau0:g} s by up "
            f"to {worst:g} s; an Allan deviation needs even sampling"
        )
    return tau0


def samples(plot: AllanDeviationPlot, data) -> tuple[np.ndarray, float]:
    """The plot's values within its range, and τ0, from its time column or
    its sample interval. The range is in time since the first sample, in τ's
    shown unit; τ0 stays that of the whole series. A DataError for times
    that do not fit the values."""
    values = np.asarray(data(plot.values), dtype=float)
    tau0 = plot.sample_interval
    since = None
    if plot.time is not None:
        times = np.asarray(data(plot.time), dtype=float)
        if len(times) != len(values):
            raise DataError(
                f"time ({plot.time.column}) has {len(times)} values, values "
                f"({plot.values.column}) has {len(values)}"
            )
        tau0 = sample_interval(times)
        since = times - times[0]
    if plot.x_range is not None:
        if since is None:
            since = np.arange(values.size) * tau0
        values = values[within(scale(since, plot.x_conversion), plot.x_range)]
    return values, tau0


def allan_axes() -> dict[str, AxisSpec]:
    """The axes an Allan deviation is read on: log-log, τ against σ_y(τ)."""
    return {
        "x": AxisSpec(label=r"$\tau$", unit="s", scale="log"),
        "y": AxisSpec(label=r"$\sigma_y(\tau)$", scale="log"),
    }
