"""Units and a range per plot (decision 0041): the one place for the arithmetic.

The renderer, the code generator, the fits and the GUI all convert through
these functions, and the code generator writes the very same operations
into the script, so that preview and script compute the same numbers bit
for bit; the pixel equivalence test holds them to it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from figscribe.model import ColumnRef, Conversion

WHOLE = 1e-9
"""How close 1 / factor must come to a whole number to be divided by:
1 / (1 / 3600) is 3600.0000000000005 in floating point."""


def operation(factor: float) -> tuple[str, float] | None:
    """How a factor is applied: ("/", 3600) when its inverse is a whole
    number above 1, as a person would write it, else ("*", factor); None
    for 1, which changes nothing."""
    if factor == 1.0:
        return None
    inverse = 1.0 / factor
    whole = round(inverse)
    if whole > 1 and abs(inverse - whole) <= WHOLE * whole:
        return ("/", whole)
    return ("*", factor)


def _apply(values: np.ndarray, factor: float) -> np.ndarray:
    how = operation(factor)
    if how is None:
        return values
    op, number = how
    return values / number if op == "/" else values * number


def convert(values, conversion: Conversion | None) -> np.ndarray:
    """`values` as shown: (value − start) × factor, the start being the
    smallest value (NaN skipped) when counting from the start."""
    values = np.asarray(values, dtype=float)
    if conversion is None:
        return values
    if conversion.from_start:
        values = values - np.nanmin(values)
    return _apply(values, conversion.factor)


def scale(errors, conversion: Conversion | None) -> np.ndarray:
    """Errors or a spread as shown: scaled with their axis, never shifted."""
    errors = np.asarray(errors, dtype=float)
    return errors if conversion is None else _apply(errors, conversion.factor)


def start(values, conversion: Conversion | None) -> float:
    """The raw value shown as 0 by a conversion counting from the start."""
    if conversion is None or not conversion.from_start:
        return 0.0
    return float(np.nanmin(np.asarray(values, dtype=float)))


def expression(name: str, conversion: Conversion) -> str:
    """The script's expression for the column `name` as shown, e.g.
    "(t - np.nanmin(t)) / 3600"; the same operations as `convert`."""
    text = f"{name} - np.nanmin({name})" if conversion.from_start else name
    how = operation(conversion.factor)
    if how is None:
        return text
    op, number = how
    if conversion.from_start:
        text = f"({text})"
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


def plot_data(plot, data: Callable[[ColumnRef], np.ndarray]) -> PlotData:
    """The plot's columns converted to the units it shows them in, every row
    of the file, and which rows its x range keeps."""
    x = convert(data(plot.x), plot.x_conversion)
    xerr = getattr(plot, "xerr", None)
    yerr = getattr(plot, "yerr", None)
    return PlotData(
        x=x,
        y=convert(data(plot.y), plot.y_conversion),
        xerr=None if xerr is None else scale(data(xerr), plot.x_conversion),
        yerr=None if yerr is None else scale(data(yerr), plot.y_conversion),
        used=within(x, plot.x_range),
    )
