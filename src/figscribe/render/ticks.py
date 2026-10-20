"""Tick decisions shared by the renderer and the code generator.

Both ask these functions what to do, so the preview and the generated script
cannot drift apart; the script gets the answers written out as plain
Matplotlib calls.
"""

from __future__ import annotations

from typing import Literal

from figscribe.model import AxisSpec, Figure

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
