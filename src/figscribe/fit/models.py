"""The predefined fit models: an expression each, and a start-value guess.

Every predefined model is an ordinary expression in the fit language, so it is
evaluated, shown and turned into generated code exactly like a user's own.
"""

from __future__ import annotations

import numpy as np

from figscribe.fit.expression import FitError

PREDEFINED: dict[str, tuple[str, list[str]]] = {
    "linear": ("a * x + b", ["a", "b"]),
    "gaussian": (
        "a * exp(-(x - mu)**2 / (2 * sigma**2)) + c",
        ["a", "mu", "sigma", "c"],
    ),
    "lorentzian": (
        "a * gamma**2 / ((x - x0)**2 + gamma**2) + c",
        ["a", "x0", "gamma", "c"],
    ),
    "exponential": ("a * exp(-x / tau) + c", ["a", "tau", "c"]),
}
"""Gaussian: height a, width sigma. Lorentzian: height a, half width gamma (HWHM).
Exponential: decay for tau > 0, growth for tau < 0. Peaks and the exponential
carry a constant background c, as real measurements almost always do."""


def predefined(name: str, degree: int | None) -> tuple[str, list[str]]:
    """Expression and parameter names of a predefined model."""
    if name == "polynomial":
        if degree is None:
            raise FitError("a polynomial fit needs a degree")
        terms = ["c0", "c1 * x", *(f"c{k} * x**{k}" for k in range(2, degree + 1))]
        return " + ".join(terms), [f"c{k}" for k in range(degree + 1)]
    return PREDEFINED[name]


def guess(
    name: str, degree: int | None, x: np.ndarray, y: np.ndarray
) -> dict[str, float]:
    """Start values estimated from the data; always finite, never raising."""
    order = np.argsort(x)
    x, y = x[order], y[order]
    if name in ("linear", "polynomial"):
        deg = 1 if name == "linear" else degree
        names = ["b", "a"] if name == "linear" else [f"c{k}" for k in range(deg + 1)]
        coeffs = np.zeros(deg + 1)
        if x.size > deg and np.ptp(x) > 0:
            coeffs = np.polyfit(x, y, deg)[::-1]
        elif y.size:
            coeffs[0] = np.mean(y)
        return _finite(dict(zip(names, coeffs, strict=True)))
    if name in ("gaussian", "lorentzian"):
        return _finite(_peak(name, x, y))
    return _finite(_exponential(x, y))


def _peak(name: str, x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    width_name = "sigma" if name == "gaussian" else "gamma"
    if y.size == 0:
        return {
            "a": 1.0,
            "mu" if name == "gaussian" else "x0": 0.0,
            width_name: 1.0,
            "c": 0.0,
        }
    c = _ends(y).mean()
    dip = (c - y.min()) > (y.max() - c)
    i = int(np.argmin(y) if dip else np.argmax(y))
    a = y[i] - c
    above = x[(y - c) / a > 0.5] if a != 0 else x[i : i + 1]
    fwhm = np.ptp(above) if above.size > 1 else np.ptp(x) / 10
    if fwhm <= 0:
        fwhm = 1.0
    width = fwhm / (2 * np.sqrt(2 * np.log(2))) if name == "gaussian" else fwhm / 2
    centre = "mu" if name == "gaussian" else "x0"
    return {"a": a, centre: x[i], width_name: width, "c": c}


def _exponential(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    span = np.ptp(x) if x.size else 0.0
    fallback = {
        "a": 1.0,
        "tau": span / 2 or 1.0,
        "c": float(np.mean(y)) if y.size else 0.0,
    }
    if x.size < 3 or span == 0:
        return fallback
    # The flat end lies near the background: the one with the smaller slope.
    n = max(3, x.size // 5)
    left = abs(np.polyfit(x[:n], y[:n], 1)[0])
    right = abs(np.polyfit(x[-n:], y[-n:], 1)[0])
    flat, steep = (y[-n:], y[:n]) if right <= left else (y[:n], y[-n:])
    # Just beyond the flat end, so that y - c keeps one sign throughout.
    c = flat.mean() - 0.05 * (steep.mean() - flat.mean())
    z = y - c
    sign = np.sign(steep.mean() - flat.mean()) or 1.0
    keep = z * sign > 0
    if keep.sum() < 2:
        return fallback
    slope, intercept = np.polyfit(x[keep], np.log(z[keep] * sign), 1)
    if slope == 0:
        return fallback
    return {"a": sign * np.exp(intercept), "tau": -1 / slope, "c": c}


def _ends(y: np.ndarray) -> np.ndarray:
    n = max(1, y.size // 10)
    return np.concatenate([y[:n], y[-n:]])


def _finite(values: dict[str, float]) -> dict[str, float]:
    return {k: float(v) if np.isfinite(v) else 1.0 for k, v in values.items()}
