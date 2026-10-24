"""Tick decisions shared by the renderer and the code generator.

Both ask these functions what to do, so the preview and the generated script
cannot drift apart; the script gets the answers written out as plain
Matplotlib calls.
"""

from __future__ import annotations

import math
from typing import Literal

from matplotlib.ticker import AutoLocator

from figscribe.model import AxisSpec, Figure

MAX_MAJOR_TICKS = 50
"""Per axis. On a 175 mm double-column axis that is one every 3.5 mm, closer
than any tick numbers fit; each tick costs about 3 ms per redraw."""

MAX_MINOR_TICKS = 250
"""Per axis. On 175 mm that is one every 0.7 mm; denser ticks merge into a grey
band. Each costs about 1.4 ms per redraw."""

PREFIXES = {"p": -12, "n": -9, "µ": -6, "m": -3, "k": 3, "M": 6, "G": 9, "T": 12}
"""SI prefixes and their powers of ten."""


def tick_style(figure: Figure) -> dict[str, object]:
    """The rcParams for the figure's tick style; empty for Matplotlib's own."""
    style: dict[str, object] = {}
    if figure.tick_direction is not None:
        style["xtick.direction"] = figure.tick_direction
        style["ytick.direction"] = figure.tick_direction
    if figure.ticks_all_sides:
        style["xtick.top"] = True
        style["ytick.right"] = True
    return style


def scaling(spec: AxisSpec) -> tuple[str, str] | None:
    """How tick values are turned into the numbers shown, as the script writes
    it: ("/", "1e3") for kHz, ("*", "1e3") for mV, ("*", "1") for plain
    numbers on a stepped log axis; None when Matplotlib's own labels stay."""
    if spec.tick_labels is not None:
        return None
    if spec.prefix is not None:
        power = PREFIXES[spec.prefix]
        return ("/", f"1e{power}") if power > 0 else ("*", f"1e{-power}")
    if spec.scale == "log" and spec.major_step is not None and spec.ticks is None:
        # Matplotlib would write 1350 as 1.35×10³ on a log axis.
        return ("*", "1")
    return None


def shown(value: float, how: tuple[str, str]) -> str:
    """A tick value as the axis shows it; the script's formatter does the same."""
    op, factor = how
    number = value / float(factor) if op == "/" else value * float(factor)
    return f"{number:g}"


def silent_minor_labels(spec: AxisSpec) -> bool:
    """Whether minor ticks must lose their labels: a log axis labels them
    itself when it spans less than a decade, ignoring a divisor."""
    return spec.scale == "log" and scaling(spec) is not None


Minor = tuple[Literal["off", "on", "parts", "step"], float | int | None]


def minor_ticks(spec: AxisSpec) -> Minor:
    """How the minor ticks are made.

    "parts": AutoMinorLocator(n), on linear axes; "step": MultipleLocator at
    a fixed distance, on a log axis with a fixed major step, where
    AutoMinorLocator refuses to work; "on" leaves them to Matplotlib (also on
    a log axis without a major step); "off" hides them.
    """
    if not spec.minor_ticks:
        return ("off", None)
    if spec.minor_divisions is None:
        return ("on", None)
    if spec.scale != "log":
        return ("parts", spec.minor_divisions)
    if spec.major_step is not None and spec.ticks is None:
        return ("step", spec.major_step / spec.minor_divisions)
    return ("on", None)


def too_many_ticks(
    spec: AxisSpec, interval: tuple[float, float]
) -> tuple[str, str] | None:
    """The field to blame and why, if the axis's own tick step or divisions
    would place more ticks within `interval` than can be drawn; None if not.

    Matplotlib only warns about such counts and then spends minutes drawing
    them. Ticks it places on its own are never this many, so only what the
    model sets is counted, and only ticks inside the range, as the user sees.
    """
    low, high = sorted(interval)
    how = scaling(spec) or ("*", "1")
    span = f"from {shown(low, how)} to {shown(high, how)}"
    if spec.ticks is None and spec.major_step is not None:
        count = _multiples(low, high, spec.major_step)
        if count > MAX_MAJOR_TICKS:
            return (
                "major_step",
                f"major ticks every {shown(spec.major_step, how)} {span} would be "
                f"{_number(count)} major ticks; at most {MAX_MAJOR_TICKS} can be drawn",
            )
    if spec.minor_divisions is None or minor_ticks(spec)[0] not in ("parts", "step"):
        return None
    if spec.ticks is None and spec.major_step is not None:
        major = spec.major_step
    elif spec.ticks is not None and len(spec.ticks) >= 2:
        major = abs(spec.ticks[1] - spec.ticks[0])  # what AutoMinorLocator uses
    elif spec.scale == "linear":
        auto = AutoLocator().tick_values(low, high)
        major = auto[1] - auto[0]
    else:
        return None
    parts = spec.minor_divisions
    count = (high - low) / major * (parts - 1) if major > 0 else 0.0
    if count > MAX_MINOR_TICKS:
        return (
            "minor_divisions",
            f"{parts - 1} minor ticks between major ones {span} would be "
            f"{_number(count)} minor ticks; at most {MAX_MINOR_TICKS} can be drawn",
        )
    return None


def _multiples(low: float, high: float, step: float) -> float:
    """How many whole multiples of `step` lie within low..high."""
    if not (high - low) / step < 1e15:  # floor and ceil fail on inf
        return math.inf
    # The tolerance keeps 0.3 / 0.1 = 2.9999999999999996 a whole step.
    return math.floor(high / step + 1e-9) - math.ceil(low / step - 1e-9) + 1


def _number(count: float) -> str:
    return f"{count:.0f}" if math.isfinite(count) else "countless"


def ticks_that_fit(spec: AxisSpec, interval: tuple[float, float]) -> AxisSpec:
    """`spec` without the tick step or divisions that would give too many
    ticks within `interval`; Matplotlib then places those ticks itself."""
    while (problem := too_many_ticks(spec, interval)) is not None:
        spec = spec.model_copy(update={problem[0]: None})
    return spec
