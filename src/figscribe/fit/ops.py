"""Running a fit as one undoable command."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from figscribe.commands import CommandError, Macro, SetField, find
from figscribe.fit.expression import FitError
from figscribe.fit.run import initial_guess, parameter_names, run_fit
from figscribe.model import ColumnRef, ErrorbarPlot, ExpressionFit, FitCurve, Project
from figscribe.model.validate import FITTABLE

DataProvider = Callable[[ColumnRef], np.ndarray]


def refit(project: Project, fit_id: str, data: DataProvider) -> Macro:
    """Fit the FitCurve `fit_id` to its target's data; return the change.

    The start values actually used are stored with the result: stored ones
    for the model's parameters win, the rest are guessed from the data. The
    project then holds everything the generated script needs to call
    curve_fit with the same input and get the same result.
    """
    fit = _get(project, fit_id)
    if not isinstance(fit, FitCurve):
        raise FitError(f"{fit_id!r} is not a fit")
    target = _get(project, fit.target)
    if not isinstance(target, FITTABLE):
        raise FitError(
            f"the fit's target is a {target.kind!r}, which has no x and y data"
        )

    x, y = data(target.x), data(target.y)
    yerr = (
        data(target.yerr) if isinstance(target, ErrorbarPlot) and target.yerr else None
    )

    names = parameter_names(fit.model)
    stored = {k: v for k, v in fit.initial_values.items() if k in names}
    p0 = {**initial_guess(fit.model, x, y), **stored}
    result = run_fit(fit.model, p0, x, y, yerr)

    label = "expression" if isinstance(fit.model, ExpressionFit) else fit.model.name
    return Macro(
        f"Fit {label}",
        [
            SetField(fit_id, ("initial_values",), p0),
            SetField(fit_id, ("result",), result),
        ],
    )


def _get(project: Project, oid: str):
    try:
        return find(project, oid)
    except CommandError as exc:
        raise FitError(str(exc)) from exc
