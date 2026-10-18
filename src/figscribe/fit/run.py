"""Running a fit: from a model and data to a FitResult."""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping

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
    max_evaluations: int | None = None,
) -> FitResult:
    """Fit `model` to the data with scipy.optimize.curve_fit.

    With `yerr`, the points are weighted by it as absolute 1-sigma errors and
    the reduced chi-square is reported. Without, the uncertainties are scaled
    by the scatter of the residuals and there is no chi-square to report.
    Points with a non-finite value are dropped. A fit that does not converge
    is recorded with converged=False, not raised: the GUI shows it, and the
    start values are kept so the user can adjust them.
    """
    f, names = _compiled(model)
    p0 = _start_values(names, initial_values)
    x, y, yerr = _data(x, y, yerr)
    if x.size <= len(names):
        raise FitError(
            f"a fit with {len(names)} parameters needs more than "
            f"{len(names)} valid points, got {x.size}"
        )
    if not np.all(np.isfinite(f(x, *p0))):
        raise FitError("the model is not finite at the start values for every point")

    with warnings.catch_warnings(), np.errstate(all="ignore"):
        # An inestimable covariance comes back as inf; that is reported below.
        warnings.simplefilter("ignore", OptimizeWarning)
        try:
            popt, pcov = curve_fit(
                f,
                x,
                y,
                p0=p0,
                sigma=yerr,
                absolute_sigma=yerr is not None,
                maxfev=max_evaluations or 0,
            )
        except RuntimeError:
            return FitResult(
                parameters=dict(zip(names, p0, strict=True)),
                uncertainties=dict.fromkeys(names, math.inf),
                reduced_chi_square=None,
                converged=False,
            )

    variances = np.diag(pcov)
    errors = np.where(np.isfinite(variances) & (variances >= 0), variances, np.inf)
    chi2 = None
    if yerr is not None:
        residuals = (y - f(x, *popt)) / yerr
        chi2 = float(np.sum(residuals**2) / (x.size - len(names)))
    return FitResult(
        parameters={n: float(v) for n, v in zip(names, popt, strict=True)},
        uncertainties={
            n: float(np.sqrt(e)) for n, e in zip(names, errors, strict=True)
        },
        reduced_chi_square=chi2,
        converged=bool(np.all(np.isfinite(popt))),
    )


def _compiled(model: FitModel) -> tuple[Model, list[str]]:
    source, names = source_of(model)
    return expression.compile_expression(source, names), names


def _start_values(names: list[str], given: Mapping[str, float]) -> list[float]:
    for name in given:
        if name not in names:
            raise FitError(
                f"unknown parameter {name!r}; the model has {', '.join(names)}"
            )
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
