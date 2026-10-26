"""Fits: predefined models and user expressions, run with curve_fit.

Every model is an expression in a small, safe language (see `expression`); the
predefined ones are named expressions with a start-value guess. `run_fit` only
computes a FitResult; `refit` wraps it in a command for the undo history.
"""

from figscribe.fit.expression import (
    ExpressionError,
    FitError,
    compile_expression,
    free_names,
)
from figscribe.fit.ops import add_fit, refit, set_left_out, update_fit
from figscribe.fit.run import (
    evaluate,
    free_parameters,
    in_range,
    initial_guess,
    kept,
    numpy_source,
    outliers,
    parameter_names,
    run_fit,
    source_of,
    within,
)

__all__ = [
    "ExpressionError",
    "add_fit",
    "FitError",
    "compile_expression",
    "evaluate",
    "free_names",
    "free_parameters",
    "in_range",
    "kept",
    "initial_guess",
    "numpy_source",
    "outliers",
    "parameter_names",
    "refit",
    "run_fit",
    "set_left_out",
    "source_of",
    "update_fit",
    "within",
]
