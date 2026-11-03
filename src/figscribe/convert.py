"""Units and a range per plot (decision 0041): the one place for the arithmetic.

The renderer, the code generator, the fits and the GUI all convert through
these functions, and the code generator writes the very same operations
into the script, so that preview and script compute the same numbers bit
for bit; the pixel equivalence test holds them to it.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from figscribe.model import ColumnRef, Conversion

WHOLE = 1e-9
"""How close 1 / factor must come to a whole number to be divided by:
1 / (1 / 3600) is 3600.0000000000005 in floating point."""


def operation(factor: float, short: bool = False) -> tuple[str, float] | None:
    """How a factor is applied: ("/", 3600) when its inverse is a whole
    number above 1, as a person would write it, else ("*", factor); None
    for 1, which changes nothing. With `short` (the slope of a formula, which
    is never exactly what was typed), the inverse may also be a short decimal,
    7.5 for a slope of 1 / 7.5."""
    if factor == 1.0:
        return None
    inverse = 1.0 / factor
    whole = round(inverse)
    if whole > 1 and abs(inverse - whole) <= WHOLE * whole:
        return ("/", whole)
    if short and inverse > 1:
        decimal = float(f"{inverse:.6g}")
        if abs(inverse - decimal) <= WHOLE * decimal:
            return ("/", decimal)
    return ("*", factor)


def _apply(values: np.ndarray, factor: float, short: bool = False) -> np.ndarray:
    how = operation(factor, short)
    if how is None:
        return values
    op, number = how
    return values / number if op == "/" else values * number


@functools.lru_cache(maxsize=256)
def _linear(formula: str) -> tuple[float, float]:
    from figscribe.fit.expression import affine

    return affine(formula)


@functools.lru_cache(maxsize=256)
def _formula(formula: str) -> Callable[[np.ndarray], np.ndarray]:
    from figscribe.fit.expression import compile_expression

    return compile_expression(formula, ())


def linear(conversion: Conversion | None) -> tuple[float, float]:
    """The slope and the offset of a conversion: shown = slope × (value −
    start) + offset. The factor and 0 without a formula."""
    if conversion is None:
        return 1.0, 0.0
    if conversion.formula is not None:
        return _linear(conversion.formula)
    return conversion.factor, 0.0


def convert(values, conversion: Conversion | None) -> np.ndarray:
    """`values` as shown: (value − start) × factor, or the formula of that, the
    start being the smallest value (NaN skipped) when counting from the start."""
    values = np.asarray(values, dtype=float)
    if conversion is None:
        return values
    if conversion.from_start:
        values = values - start(values, conversion)
    if conversion.formula is not None:
        return _formula(conversion.formula)(values)
    return _apply(values, conversion.factor)


def scale(errors, conversion: Conversion | None) -> np.ndarray:
    """Errors or a spread as shown: scaled with their axis, never shifted."""
    errors = np.asarray(errors, dtype=float)
    if conversion is None:
        return errors
    return _apply(errors, linear(conversion)[0], conversion.formula is not None)


def start(values, conversion: Conversion | None) -> float:
    """The raw value shown as 0 by a conversion counting from the start."""
    if conversion is None or not conversion.from_start:
        return 0.0
    values = np.asarray(values, dtype=float)
    # A column of nothing but NaN has no start; its values stay NaN anyway.
    return float(np.nanmin(values)) if np.isfinite(values).any() else 0.0


def expression(name: str, conversion: Conversion) -> str:
    """The script's expression for the column `name` as shown, e.g.
    "(t - np.nanmin(t)) / 3600"; the same operations as `convert`."""
    if conversion.formula is not None:
        from figscribe.fit.expression import numpy_source

        shifted = f"{name} - np.nanmin({name})" if conversion.from_start else name
        return numpy_source(conversion.formula, shifted)
    if not conversion.from_start:
        return scaled(name, conversion.factor)
    shifted = f"{name} - np.nanmin({name})"
    if operation(conversion.factor) is None:
        return shifted
    return scaled(f"({shifted})", conversion.factor)


def scale_expression(text: str, conversion: Conversion) -> str:
    """The script's expression for the errors, or the durations, `text` shown
    with `conversion`: scaled, never shifted, the same operation as `scale`."""
    return scaled(text, linear(conversion)[0], conversion.formula is not None)


def scaled(text: str, factor: float, short: bool = False) -> str:
    """The script's expression `text` scaled by `factor`, as `scale` does it:
    "dU * 1000", "m * tau0 / 60"."""
    how = operation(factor, short)
    if how is None:
        return text
    op, number = how
    short = f"{number:g}"
    # The short form only where it is the very same number: 1000, not 1e+03.
    written = short if float(short) == number and "e" not in short else repr(number)
    return f"{text} {op} {written}"


def within(values: np.ndarray, ends: tuple[float, float] | None) -> np.ndarray:
    """Which values lie within `ends`, both included; all of them for None."""
    if ends is None:
        return np.ones(values.shape, dtype=bool)
    low, high = ends
    return (values >= low) & (values <= high)


@dataclass(frozen=True)
class PlotData:
    """The columns of a line, scatter or error bar plot as it shows them."""

    x: np.ndarray
    y: np.ndarray
    xerr: np.ndarray | None
    yerr: np.ndarray | None
    used: np.ndarray
    """Which rows lie within the plot's x range; all for none."""
    reduced: bool = False
    """The columns are the plot's reduced points (decision 0045), not its rows
    of the file: the range and the rows left out are already taken out."""
    rows: np.ndarray | None = None
    """For reduced points, the first row of the file of each."""

    def rows_kept(self, left_out) -> np.ndarray:
        """Which of the points a fit may use: the rows within the plot's range
        that are not in `left_out`; every point of a reduced plot, where those
        are already taken out."""
        if self.reduced:
            return np.ones(len(self.x), dtype=bool)
        from figscribe.fit.run import kept

        return kept(len(self.x), left_out) & self.used


def plot_data(plot, data: Callable[[ColumnRef], np.ndarray]) -> PlotData:
    """The plot's columns converted to the units it shows them in, every row
    of the file, and which rows its x range keeps; with a reduction, its
    reduced points."""
    x = convert(data(plot.x), plot.x_conversion)
    xerr = getattr(plot, "xerr", None)
    yerr = getattr(plot, "yerr", None)
    shown = PlotData(
        x=x,
        y=convert(data(plot.y), plot.y_conversion),
        xerr=None if xerr is None else scale(data(xerr), plot.x_conversion),
        yerr=None if yerr is None else scale(data(yerr), plot.y_conversion),
        used=within(x, plot.x_range),
    )
    if plot.reduction is None:
        return shown
    from figscribe.reduce import reduced

    return reduced(plot, shown)
