"""A function drawn from its formula (decision 0078).

What the renderer, the code generator, the panel and the problem list all ask:
whether the formula can be read, the values of its names, where it is drawn and
whether it scales the axis. The formula is the safe language of own fit
formulas; its text is never run.
"""

from __future__ import annotations

import ast
from collections.abc import Callable

import numpy as np

from figscribe.commands import CommandError, Macro, SetField, find
from figscribe.fit.expression import (
    VARIABLE,
    FitError,
    compile_expression,
    free_names,
)
from figscribe.model import (
    AllanDeviationPlot,
    ColorMesh,
    Figure,
    FitCurve,
    FunctionPlot,
    Histogram,
    ImagePlot,
    Project,
    ResidualPlot,
)
from figscribe.model.sharing import sharing_group, typed_limits
from figscribe.model.validate import FITTABLE, axis_values

DATA = (
    *FITTABLE,
    Histogram,
    AllanDeviationPlot,
    ImagePlot,
    ColorMesh,
    FitCurve,
    ResidualPlot,
)
"""What shows data or comes from them: an axis with one of these is scaled by
them, not by a function."""


def names(expression: str) -> list[str]:
    """The names a value is needed for, as they first appear; a CommandError, in
    words, for a formula that cannot be read."""
    try:
        found = free_names(expression)
        if "np" in found:  # the script's name for NumPy
            raise FitError("'np' is reserved and cannot be a name in a formula")
        compile_expression(expression, found)
    except FitError as exc:
        raise CommandError(f"the formula cannot be read: {exc}") from None
    return found


def values(function: FunctionPlot) -> dict[str, float]:
    """The value of every name in the formula."""
    return {n: function.parameters.get(n, 1.0) for n in names(function.expression)}


def problem(function: FunctionPlot) -> str | None:
    """Why the formula cannot be drawn; None if it can."""
    try:
        names(function.expression)
    except CommandError as exc:
        return str(exc)
    return None


def uses_x(expression: str) -> bool:
    """Whether the formula depends on x, once it can be read."""
    return any(
        isinstance(node, ast.Name) and node.id == VARIABLE
        for node in ast.walk(ast.parse(expression, mode="eval"))
    )


def evaluator(function: FunctionPlot) -> Callable[[np.ndarray], np.ndarray] | None:
    """x to y; None for a formula that cannot be read."""
    if problem(function) is not None:
        return None
    given = values(function)
    model = compile_expression(function.expression, list(given))
    return lambda x: model(x, *given.values())


def x_span(
    figure: Figure, index: int, function: FunctionPlot, data
) -> tuple[float, float] | None:
    """From where to where the function is drawn: its own range, else the range
    typed on the x axis, else that of the data on it; None where there is none."""
    if function.curve_range is not None:
        return function.curve_range
    if (typed := typed_limits(figure, index, "x")) is not None:
        return typed
    if data is None:
        return None
    found = axis_values(figure, index, "x", data, functions=False)
    found = found[np.isfinite(found)]
    if figure.axes[index].x.scale == "log":
        found = found[found > 0]
    if not found.size or not found.min() < found.max():
        return None
    return float(found.min()), float(found.max())


def sets_limits(figure: Figure, index: int, function: FunctionPlot) -> bool:
    """Whether the function scales its y axis: only where no data do."""
    axes = figure.axes[index]
    right = function.axis == "right" and axes.y_right is not None
    group = [index] if right else sharing_group(figure, index, "y")
    return not any(
        isinstance(artist, DATA)
        and (artist.axis == "right" and figure.axes[i].y_right is not None) == right
        for i in group
        for artist in figure.axes[i].artists
    )


def new_function(expression: str) -> FunctionPlot:
    """A function with every name of the formula at 1."""
    return FunctionPlot(
        expression=expression, parameters=dict.fromkeys(names(expression), 1.0)
    )


def set_expression(project: Project, function_id: str, expression: str) -> Macro:
    """Change the formula: names that remain keep their values, new ones start
    at 1 and those gone are dropped, in one step."""
    function = find(project, function_id)
    if not isinstance(function, FunctionPlot):
        raise CommandError(f"{function_id!r} is not a function")
    given = {n: function.parameters.get(n, 1.0) for n in names(expression)}
    return Macro(
        "Change the formula",
        [
            SetField(function_id, ("expression",), expression),
            SetField(function_id, ("parameters",), given),
        ],
    )
