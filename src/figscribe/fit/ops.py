"""Running a fit as one undoable command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from figscribe.commands import CommandError, InsertItem, Macro, SetField, find
from figscribe.fit.expression import FitError
from figscribe.fit.run import (
    evaluate,
    in_range,
    initial_guess,
    kept,
    parameter_names,
    run_fit,
    within,
)
from figscribe.model import (
    Axes,
    AxisSpec,
    ColumnRef,
    ErrorbarPlot,
    ExpressionFit,
    Figure,
    FitCurve,
    Project,
    ResidualPlot,
)
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
    used = in_range(x, fit.fit_range) & kept(len(x), target.left_out)
    x, y = np.asarray(x, dtype=float)[used], np.asarray(y, dtype=float)[used]
    yerr = None if yerr is None else np.asarray(yerr, dtype=float)[used]

    names = parameter_names(fit.model)
    stored = {k: v for k, v in fit.initial_values.items() if k in names}
    # A guess may fall outside a bound the user set; a stored value may not.
    guessed = within(initial_guess(fit.model, x, y), fit.parameter_bounds)
    p0 = {**guessed, **stored}
    result = run_fit(
        fit.model, p0, x, y, yerr, fixed=fit.fixed, bounds=fit.parameter_bounds
    )

    label = "expression" if isinstance(fit.model, ExpressionFit) else fit.model.name
    return Macro(
        f"Fit {label}",
        [
            SetField(fit_id, ("initial_values",), p0),
            SetField(fit_id, ("result",), result),
        ],
    )


EDITABLE = (
    "model",
    "initial_values",
    "fixed",
    "parameter_bounds",
    "fit_range",
    "extend_curve",
    "outside_as_left_out",
    "result",
    "label",
)
"""What the fit dialog changes on a fit that is already there."""


def update_fit(project: Project, fit_id: str, changed: FitCurve) -> Macro:
    """Give the fit `fit_id` the model, start values, held parameters, bounds,
    result and label of `changed`, as one step."""
    fit = _get(project, fit_id)
    if not isinstance(fit, FitCurve):
        raise FitError(f"{fit_id!r} is not a fit")
    return Macro(
        "Change the fit",
        [
            SetField(fit_id, (name,), getattr(changed, name))
            for name in EDITABLE
            if getattr(changed, name) != getattr(fit, name)
        ],
    )


def set_left_out(
    project: Project, plot_id: str, rows: list[int], data: DataProvider
) -> Macro:
    """Leave out `rows` of the plot `plot_id` (counted from 0), and fit every
    fit of the plot again, as one step. A FitError, changing nothing, if a fit
    cannot be run without them."""
    plot = _get(project, plot_id)
    if not isinstance(plot, FITTABLE):
        raise FitError(f"{plot_id!r} is not a plot of points")
    rows = sorted(set(rows))
    added, back = set(rows) - set(plot.left_out), set(plot.left_out) - set(rows)
    if len(added) == 1 and not back:
        description = f"Leave out row {min(added) + 1}"
    elif len(back) == 1 and not added:
        description = f"Take row {min(back) + 1} back in"
    else:
        description = "Change the rows left out"
    staging = project.model_copy(deep=True)
    steps = [SetField(plot_id, ("left_out",), rows)]
    steps[0].apply(staging)
    fits = [
        artist.id
        for figure in staging.figures
        for axes in figure.axes
        for artist in axes.artists
        if isinstance(artist, FitCurve) and artist.target == plot_id
    ]
    for fit_id in fits:
        again = refit(staging, fit_id, data)
        again.apply(staging)
        steps += again.steps
    return Macro(description, steps)


@dataclass(frozen=True)
class Residuals:
    """How a fit meets the points it was fitted to."""

    used: int
    """Points fitted: finite, in the fit range, not left out."""
    total: int
    """Rows of the plot's data."""
    rms: float
    """Root mean square of data minus fit, in the unit of y."""
    largest: float
    """The residual farthest from zero, with its sign."""
    row: int
    """Its data row, counted from 0."""


def residuals(project: Project, fit_id: str, data: DataProvider) -> Residuals | None:
    """The residuals of a fit that has been run; None before."""
    fit = _get(project, fit_id)
    if not isinstance(fit, FitCurve) or fit.result is None:
        return None
    if not set(parameter_names(fit.model)) <= set(fit.result.parameters):
        return None  # a result from a file that lacks some parameters
    target = _get(project, fit.target)
    x = np.asarray(data(target.x), dtype=float)
    y = np.asarray(data(target.y), dtype=float)
    used = in_range(x, fit.fit_range) & kept(len(x), target.left_out)
    used &= np.isfinite(x) & np.isfinite(y)
    if not used.any():
        return None
    off = y[used] - evaluate(fit.model, fit.result.parameters, x[used])
    farthest = int(np.argmax(np.abs(off)))
    return Residuals(
        used=int(used.sum()),
        total=len(x),
        rms=float(np.sqrt(np.mean(off**2))),
        largest=float(off[farthest]),
        row=int(np.flatnonzero(used)[farthest]),
    )


RESIDUAL_HEIGHT_MM = 20.0
"""How much taller a figure gets when a residual panel is added below."""


def add_fit(project: Project, fit: FitCurve, residuals: bool = False) -> Macro:
    """Put `fit` next to its target and, with `residuals`, its residuals below.

    The residuals go into an empty panel right below the target's if there is
    one (as the "data, fit and residuals" layout has); otherwise a row is
    added at the bottom, the figure grows by RESIDUAL_HEIGHT_MM and shares x
    by column. The x label moves down to the residual panel, which is now the
    one showing x tick labels.
    """
    figure, axes = _home(project, fit.target)
    target = next(a for a in axes.artists if a.id == fit.target)
    if target.axis != fit.axis:
        fit = fit.model_copy(update={"axis": target.axis})  # drawn where its data is
    steps: list = [InsertItem(axes.id, "artists", fit)]
    name = fit.label or _model_name(fit)
    if not residuals:
        return Macro(f"Add {name}", steps)

    plot = ResidualPlot(target=fit.id)
    x_spec = axes.x.model_copy()
    y_spec = AxisSpec(label="Residual", unit=axes.y.unit)
    below = _empty_panel_below(figure, axes)
    if below is not None:
        steps.append(InsertItem(below.id, "artists", plot))
        for field, spec in (("x", x_spec), ("y", y_spec)):
            if getattr(below, field).label is None:
                steps.append(SetField(below.id, (field,), spec))
    else:
        layout = figure.layout
        ratios = layout.height_ratios or [3.0] * layout.rows
        panel = Axes(
            row=layout.rows,
            col=axes.col,
            colspan=axes.colspan,
            x=x_spec,
            y=y_spec,
            artists=[plot],
        )
        steps += [
            SetField(figure.id, ("layout", "rows"), layout.rows + 1),
            SetField(figure.id, ("layout", "height_ratios"), [*ratios, 1.0]),
            SetField(figure.id, ("height_mm",), figure.height_mm + RESIDUAL_HEIGHT_MM),
            InsertItem(figure.id, "axes", panel),
        ]
        if layout.share_x == "none":
            steps.append(SetField(figure.id, ("layout", "share_x"), "col"))
    if axes.x.label is not None or axes.x.unit is not None:
        steps.append(
            SetField(
                axes.id, ("x",), axes.x.model_copy(update={"label": None, "unit": None})
            )
        )
    return Macro(f"Add {name} with residuals", steps)


def _home(project: Project, target_id: str) -> tuple[Figure, Axes]:
    for figure in project.figures:
        for axes in figure.axes:
            if any(a.id == target_id for a in axes.artists):
                target = next(a for a in axes.artists if a.id == target_id)
                if not isinstance(target, FITTABLE):
                    raise FitError(f"a {target.kind} plot cannot be fitted")
                return figure, axes
    raise FitError(f"no plot with id {target_id!r} to fit")


def _empty_panel_below(figure: Figure, axes: Axes) -> Axes | None:
    for other in figure.axes:
        right_place = other.row == axes.row + axes.rowspan and other.col == axes.col
        if right_place and other.colspan == axes.colspan and not other.artists:
            return other
    return None


def _model_name(fit: FitCurve) -> str:
    if isinstance(fit.model, ExpressionFit):
        return "fit"
    return f"{fit.model.name} fit"


def _get(project: Project, oid: str):
    try:
        return find(project, oid)
    except CommandError as exc:
        raise FitError(str(exc)) from exc
