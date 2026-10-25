"""Running a fit: from a model and data to a FitResult."""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping, Sequence

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit

from figscribe.fit import expression, models
from figscribe.fit.expression import FitError, Model
from figscribe.model import ExpressionFit, FitModel, FitResult


def source_of(model: FitModel) -> tuple[str, list[str]]:
    """The model's expression and its parameter names, in order."""
    if isinstance(model, ExpressionFit):
        return model.expression, list(model.parameters)
    return models.predefined(model.name, model.degree)


def parameter_names(model: FitModel) -> list[str]:
    """The model's parameters, in the order curve_fit sees them."""
    _, names = _compiled(model)
    return names


def numpy_source(model: FitModel | str) -> str:
    """The model as a NumPy expression in x, for the code generator."""
    source = model if isinstance(model, str) else source_of(model)[0]
    return expression.numpy_source(source)


def evaluate(model: FitModel, parameters: Mapping[str, float], x) -> np.ndarray:
    """The model's values at `x`, e.g. to draw the fitted curve."""
    f, names = _compiled(model)
    return f(np.asarray(x, dtype=float), *(parameters[n] for n in names))


def initial_guess(model: FitModel, x, y) -> dict[str, float]:
    """Start values for every parameter, estimated from the data where possible.

    Expressions get 1.0 for every parameter: nothing is known about them.
    """
    names = parameter_names(model)
    if isinstance(model, ExpressionFit):
        return dict.fromkeys(names, 1.0)
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    return models.guess(model.name, model.degree, x[valid], y[valid])


def run_fit(
    model: FitModel,
    initial_values: Mapping[str, float],
    x,
    y,
    yerr=None,
    *,
    fixed: Sequence[str] = (),
    bounds: Mapping[str, tuple[float | None, float | None]] | None = None,
    max_evaluations: int | None = None,
) -> FitResult:
    """Fit `model` to the data with scipy.optimize.curve_fit.

    With `yerr`, the points are weighted by it as absolute 1-sigma errors and
    the reduced chi-square is reported. Without, the uncertainties are scaled
    by the scatter of the residuals and there is no chi-square to report.
    Points with a non-finite value are dropped. A fit that does not converge
    is recorded with converged=False, not raised: the GUI shows it, and the
    start values are kept so the user can adjust them.

    Parameters in `fixed` keep their start value, with uncertainty 0, and do
    not count as degrees of freedom. `bounds` gives a parameter a (lower,
    upper) range, None for an open end; curve_fit then uses its bounded
    method ("trf").
    """
    f, names = _compiled(model)
    p0 = dict(zip(names, _start_values(names, initial_values), strict=True))
    free = _free(names, fixed)
    lower, upper = _bounds(free, p0, bounds or {})
    x, y, yerr = _data(x, y, yerr)
    if x.size <= len(free):
        raise FitError(
            f"a fit with {len(free)} parameters needs more than "
            f"{len(free)} valid points, got {x.size}"
        )
    if not np.all(np.isfinite(f(x, *p0.values()))):
        raise FitError("the model is not finite at the start values for every point")

    def with_fixed(x, *values):
        return f(x, *{**p0, **dict(zip(free, values, strict=True))}.values())

    bounded = any(np.isfinite(lower)) or any(np.isfinite(upper))
    options = (
        {"bounds": (lower, upper), "max_nfev": max_evaluations}
        if bounded
        else {"maxfev": max_evaluations or 0}
    )
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        # An inestimable covariance comes back as inf; that is reported below.
        warnings.simplefilter("ignore", OptimizeWarning)
        try:
            popt, pcov = curve_fit(
                with_fixed if len(free) < len(names) else f,
                x,
                y,
                p0=[p0[n] for n in free],
                sigma=yerr,
                absolute_sigma=yerr is not None,
                **options,
            )
        except RuntimeError:
            return FitResult(
                parameters=dict(p0),
                uncertainties={n: math.inf if n in free else 0.0 for n in names},
                reduced_chi_square=None,
                converged=False,
            )

    fitted = {**p0, **dict(zip(free, map(float, popt), strict=True))}
    variances = np.full(len(free), np.inf) if _singular(pcov) else np.diag(pcov)
    errors = dict(zip(free, map(float, np.sqrt(variances)), strict=True))
    chi2 = None
    if yerr is not None:
        residuals = (y - f(x, *fitted.values())) / yerr
        chi2 = float(np.sum(residuals**2) / (x.size - len(free)))
    return FitResult(
        parameters={n: float(fitted[n]) for n in names},
        uncertainties={n: errors.get(n, 0.0) for n in names},
        reduced_chi_square=chi2,
        converged=bool(np.all(np.isfinite(popt))),
    )


def in_range(x, fit_range: tuple[float, float] | None) -> np.ndarray:
    """Which points a fit over `fit_range` uses; all of them for None."""
    x = np.asarray(x, dtype=float)
    if fit_range is None:
        return np.ones(x.shape, dtype=bool)
    low, high = fit_range
    return (x >= low) & (x <= high)


def kept(count: int, left_out: Sequence[int]) -> np.ndarray:
    """Which of `count` rows are not left out; a FitError for a left-out row
    the data does not have."""
    rows = np.ones(count, dtype=bool)
    for row in left_out:
        if row >= count:
            raise FitError(f"row {row + 1} is left out, but the data has {count} rows")
        rows[row] = False
    return rows


def within(
    values: Mapping[str, float],
    bounds: Mapping[str, tuple[float | None, float | None]],
) -> dict[str, float]:
    """`values` moved into their bounds where they lie outside."""
    moved = dict(values)
    for name, (low, high) in bounds.items():
        if name in moved:
            if low is not None:
                moved[name] = max(moved[name], low)
            if high is not None:
                moved[name] = min(moved[name], high)
    return moved


MAD_TO_SIGMA = 1.4826
"""Turns a median absolute deviation into a standard deviation, for normally
distributed residuals; unlike the standard deviation it ignores the outliers."""


def outliers(
    model: FitModel,
    initial_values: Mapping[str, float],
    x,
    y,
    yerr=None,
    *,
    k: float = 3.0,
    fixed: Sequence[str] = (),
    bounds: Mapping[str, tuple[float | None, float | None]] | None = None,
    rounds: int = 10,
) -> np.ndarray:
    """Which points lie more than `k` sigma off the model fitted without them.

    Sigma is a point's error bar or, without errors, MAD_TO_SIGMA times the
    median absolute deviation of the residuals. The model is fitted again
    without the points found until they no longer change, so a point can
    also come back. A FitError if the fit itself fails.
    """
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    yerr = None if yerr is None else np.asarray(yerr, dtype=float)
    out = np.zeros(x.size, dtype=bool)
    for _ in range(rounds):
        keep = ~out
        result = run_fit(
            model,
            initial_values,
            x[keep],
            y[keep],
            None if yerr is None else yerr[keep],
            fixed=fixed,
            bounds=bounds,
        )
        residual = y - evaluate(model, result.parameters, x)
        if yerr is not None:
            scale = yerr
        else:
            kept = residual[keep & np.isfinite(residual)]
            scale = MAD_TO_SIGMA * np.median(np.abs(kept - np.median(kept)))
            if not scale > 0:
                return out  # the model meets every point: nothing lies off
        with np.errstate(all="ignore"):
            found = np.isfinite(residual) & (np.abs(residual / scale) > k)
        if np.array_equal(found, out):
            break
        out = found
    return out


def free_parameters(model: FitModel, fixed: Sequence[str]) -> list[str]:
    """The parameters curve_fit varies: the model's, less the fixed ones."""
    return _free(parameter_names(model), fixed)


def _free(names: list[str], fixed: Sequence[str]) -> list[str]:
    _known(names, fixed)
    free = [n for n in names if n not in fixed]
    if not free:
        raise FitError("every parameter is fixed; free one to fit")
    return free


def _bounds(
    free: list[str],
    start: Mapping[str, float],
    bounds: Mapping[str, tuple[float | None, float | None]],
) -> tuple[list[float], list[float]]:
    """Lower and upper bounds of the free parameters, -inf and inf for none."""
    _known(list(start), bounds)
    lower, upper = [], []
    for name in free:
        low, high = bounds.get(name, (None, None))
        low = -math.inf if low is None else float(low)
        high = math.inf if high is None else float(high)
        if not low < high:
            raise FitError(f"the lower bound of {name} is not below the upper")
        if not low <= start[name] <= high:
            raise FitError(
                f"the start value of {name}, {start[name]:g}, lies outside its "
                f"bounds ({low:g} to {high:g})"
            )
        lower.append(low)
        upper.append(high)
    return lower, upper


def _known(names: list[str], given) -> None:
    for name in given:
        if name not in names:
            raise FitError(
                f"unknown parameter {name!r}; the model has {', '.join(names)}"
            )


MAX_CONDITION = 1 / (100 * np.finfo(float).eps)
"""Above this condition number of the correlation matrix, the covariance carries
less than about two significant digits, and the uncertainties mean nothing."""


def _singular(pcov: np.ndarray) -> bool:
    """Whether the covariance cannot be estimated.

    curve_fit reports that as inf, but only when the linear algebra library
    notices: Apple's Accelerate, used by SciPy on macOS, instead returns huge
    finite values for the same degenerate fit. So check it here, independent
    of the platform, on the scale-free correlation matrix.
    """
    variances = np.diag(pcov)
    if not np.all(np.isfinite(pcov)) or np.any(variances <= 0):
        return True
    correlation = pcov / np.sqrt(np.outer(variances, variances))
    return bool(np.linalg.cond(correlation) > MAX_CONDITION)


def _compiled(model: FitModel) -> tuple[Model, list[str]]:
    source, names = source_of(model)
    return expression.compile_expression(source, names), names


def _start_values(names: list[str], given: Mapping[str, float]) -> list[float]:
    _known(names, given)
    values = []
    for name in names:
        if name not in given:
            raise FitError(f"missing start value for {name!r}")
        if not math.isfinite(given[name]):
            raise FitError(f"start value for {name!r} is not finite")
        values.append(float(given[name]))
    return values


def _data(x, y, yerr) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    arrays = [x, y] if yerr is None else [x, y, np.asarray(yerr, dtype=float)]
    if len({a.shape for a in arrays}) != 1 or x.ndim != 1:
        raise FitError("x, y and the errors must be 1-D and of the same length")
    valid = np.logical_and.reduce([np.isfinite(a) for a in arrays])
    x, y = x[valid], y[valid]
    if yerr is None:
        return x, y, None
    yerr = arrays[2][valid]
    if np.any(yerr <= 0):
        raise FitError("y errors must be positive to weight the fit")
    return x, y, yerr
