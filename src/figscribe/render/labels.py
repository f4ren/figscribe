"""Axis label and panel label text, shared by the renderer and the code
generator.

The code generator calls these at generation time and writes the resulting
string into the script, so the script needs no figscribe helper.
"""

from __future__ import annotations

from string import ascii_lowercase
from typing import Any, Literal

from figscribe.model import AxisSpec, Figure, PanelLabels
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


def panel_labels(figure: Figure) -> dict[int, str]:
    """The letter of each lettered panel, by its index in `figure.axes`.

    Grid panels in reading order, by the cell they start in: row by row, left
    to right. With `insets`, each inset right after the panel it sits in.
    """
    labels = figure.panel_labels
    if labels is None:
        return {}
    grid = sorted(
        (i for i, axes in enumerate(figure.axes) if axes.inset is None),
        key=lambda i: (figure.axes[i].row, figure.axes[i].col),
    )
    order = []
    for i in grid:
        order.append(i)
        if labels.insets:
            parent = figure.axes[i].id
            order += [
                j
                for j, axes in enumerate(figure.axes)
                if axes.inset is not None and axes.inset.parent == parent
            ]
    return {i: _lettered(labels.style, n) for n, i in enumerate(order)}


def panel_label_options(labels: PanelLabels) -> dict[str, Any]:
    """The keywords of `ax.annotate` for a panel label, after its text.

    The offset is in the label's font size, so a larger letter keeps the same
    look; outside, the constrained layout makes room for it.
    """
    outside = labels.placement == "outside"
    options: dict[str, Any] = {
        "xy": (0, 1),
        "xycoords": "axes fraction",
        "xytext": (-0.5, 0.5) if outside else (0.5, -0.5),
        "textcoords": "offset fontsize",
        "ha": "right" if outside else "left",
        "va": "bottom" if outside else "top",
    }
    if labels.fontsize is not None:
        options["fontsize"] = labels.fontsize
    if labels.bold:
        options["fontweight"] = "bold"
    return options


def _lettered(style: str, index: int) -> str:
    """The `index`-th label (from 0) in `style`: a, b, …, z, aa, ab, …"""
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = ascii_lowercase[rest] + letters
    if style == "A":
        return letters.upper()
    return style.replace("a", letters)
