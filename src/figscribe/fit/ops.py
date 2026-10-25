"""Running a fit as one undoable command."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from figscribe.commands import CommandError, InsertItem, Macro, SetField, find
from figscribe.fit.expression import FitError
from figscribe.fit.run import initial_guess, parameter_names, run_fit, within
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
