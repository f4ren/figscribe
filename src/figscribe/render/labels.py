"""Axis label text, shared by the renderer and the code generator.

The code generator calls these at generation time and writes the resulting
string into the script, so the script needs no figscribe helper.
"""

from __future__ import annotations

from typing import Literal

from figscribe.model import AxisSpec
from figscribe.render.ticks import PREFIXES

UnitFormat = Literal["parentheses", "slash", "brackets"]


def axis_label(spec: AxisSpec, unit_format: UnitFormat) -> str | None:
    """Return the label text for `spec`, with its unit joined in.

    The unit stays plain text so that it renders upright next to an italic
    quantity symbol. No label means no label, even if a unit is set: a bare
    unit on an axis says nothing about what is plotted.
    """
    if spec.label is None:
        return None
    shown = unit_shown(spec)
    if shown is None:
        return spec.label
    if unit_format == "parentheses":
        return f"{spec.label} ({shown})"
    if unit_format == "brackets":
        return f"{spec.label} [{shown}]"
    # ISO 80000: a compound unit after the slash needs parentheses, otherwise
    # "v / m/s" reads as v divided by m divided by s.
    unit = f"({shown})" if "/" in shown else shown
    return f"{spec.label} / {unit}"


def unit_shown(spec: AxisSpec) -> str | None:
    """The unit as the axis shows it: with the prefix ("kHz"), or, without a
    unit, the factor the values were divided by."""
    if spec.prefix is None:
        return spec.unit
    if spec.unit is not None:
        return f"{spec.prefix}{spec.unit}"
    return rf"$\times 10^{{{PREFIXES[spec.prefix]}}}$"
