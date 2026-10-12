"""Axis label text, shared by the renderer and the code generator.

The code generator calls these at generation time and writes the resulting
string into the script, so the script needs no figscribe helper.
"""

from __future__ import annotations

from typing import Literal

from figscribe.model import AxisSpec

UnitFormat = Literal["parentheses", "slash", "brackets"]


def axis_label(spec: AxisSpec, unit_format: UnitFormat) -> str | None:
    """Return the label text for `spec`, with its unit joined in.

    The unit stays plain text so that it renders upright next to an italic
    quantity symbol. No label means no label, even if a unit is set: a bare
    unit on an axis says nothing about what is plotted.
    """
    if spec.label is None:
        return None
    if spec.unit is None:
        return spec.label
    if unit_format == "parentheses":
        return f"{spec.label} ({spec.unit})"
    if unit_format == "brackets":
        return f"{spec.label} [{spec.unit}]"
    # ISO 80000: a compound unit after the slash needs parentheses, otherwise
    # "v / m/s" reads as v divided by m divided by s.
    unit = f"({spec.unit})" if "/" in spec.unit else spec.unit
    return f"{spec.label} / {unit}"
