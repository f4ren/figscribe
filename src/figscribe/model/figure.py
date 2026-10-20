"""Figures and their panel layout."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from figscribe.model.axes import Axes
from figscribe.model.base import Identified, StrictModel


class GridLayout(StrictModel):
    """Panel grid. Axes place themselves in it by row, col and span."""

    rows: int = Field(1, ge=1)
    cols: int = Field(1, ge=1)
    share_x: Literal["none", "col", "all"] = "none"
    share_y: Literal["none", "row", "all"] = "none"
    width_ratios: list[float] | None = None
    height_ratios: list[float] | None = None
    constrained_layout: bool = True
    hspace: float | None = Field(None, ge=0.0)
    wspace: float | None = Field(None, ge=0.0)


class Figure(Identified):
    name: str = "Figure 1"
    width_mm: float = Field(85.0, gt=0.0)
    """85 mm is a typical single journal column, 175 mm a double one."""
    height_mm: float = Field(60.0, gt=0.0)
    dpi: float = Field(300.0, gt=0.0)
    unit_format: Literal["parentheses", "slash", "brackets"] = "parentheses"
    """How axis labels carry their unit: "U (V)", "U / V" (ISO 80000) or "U [V]".

    Per figure because journals disagree; a style template sets it.
    """
    stylesheet: str | None = None
    """Name of a bundled style or a path to an .mplstyle file."""
    font_size: float | None = Field(None, gt=0.0)
    """Base font size in pt; labels, ticks and legend scale with it. None
    keeps Matplotlib's (or the style sheet's)."""
    tick_direction: Literal["in", "out", "inout"] | None = None
    """Which way the tick marks point, in every panel; None keeps Matplotlib's
    (or the style sheet's), which is "out"."""
    ticks_all_sides: bool = False
    """Tick marks also on the top and right edge of every panel, as many
    physics journals have them; the numbers stay bottom and left."""
    layout: GridLayout = Field(default_factory=GridLayout)
    axes: list[Axes] = Field(default_factory=list)
