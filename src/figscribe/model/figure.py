"""Figures and their panel layout."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from figscribe.model.axes import Axes
from figscribe.model.base import Identified, StrictModel


class GridLayout(StrictModel):
    """Panel grid. Axes place themselves in it by row, col and span."""

    rows: int = Field(1, ge=1)
    """Number of grid rows."""
    cols: int = Field(1, ge=1)
    """Number of grid columns."""
    share_x: Literal["none", "col", "all"] = "none"
    """"col" joins the x axes of panels in the same column, "all" of every panel;
    tick numbers then show only at the bottom."""
    share_y: Literal["none", "row", "all"] = "none"
    """"row" joins the y axes of panels in the same row, "all" of every panel; tick
    numbers then show only at the left."""
    width_ratios: list[float] | None = None
    """Relative widths of the columns, one number each; None makes them equal."""
    height_ratios: list[float] | None = None
    """Relative heights of the rows, one number each; None makes them equal."""
    constrained_layout: bool = True
    """Whether Matplotlib places the panels so that labels do not overlap."""
    hspace: float | None = Field(None, ge=0.0)
    """Gap between rows as a fraction of the average panel height; None lets
    Matplotlib choose."""
    wspace: float | None = Field(None, ge=0.0)
    """Gap between columns as a fraction of the average panel width; None lets
    Matplotlib choose."""


class PanelLabels(StrictModel):
    """Letters on the panels, (a), (b), (c), in reading order: row by row,
    left to right, by the cell a panel starts in."""

    style: Literal["(a)", "a)", "a", "A"] = "(a)"
    """How the letters are written; after z they go on with aa, ab."""
    bold: bool = False
    """Bold letters, as Nature and Science print them."""
    placement: Literal["outside", "inside"] = "outside"
    """"outside" puts each letter above and left of its panel's top left
    corner, "inside" just within it."""
    fontsize: float | None = Field(None, gt=0.0)
    """Font size in pt; None follows the figure."""
    insets: bool = False
    """Insets get a letter too, each right after the panel it sits in."""


class Figure(Identified):
    name: str = "Figure 1"
    """Shown in figscribe and used for the names of exported files."""
    width_mm: float = Field(85.0, gt=0.0)
    """85 mm is a typical single journal column, 175 mm a double one."""
    height_mm: float = Field(60.0, gt=0.0)
    """Height of the whole figure in mm, as printed."""
    dpi: float = Field(300.0, ge=72.0)
    """Resolution of PNG exports in dots per inch; PDF and SVG are vector graphics.

    At least that of a screen: much below it, text cannot be drawn at all.
    """
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
    frame_width: float | None = Field(None, gt=0.0)
    """Line width of the frame around every panel in pt; None keeps
    Matplotlib's (or the style sheet's), which is 0.8."""
    tick_width: float | None = Field(None, gt=0.0)
    """Line width of the major tick marks in pt; None keeps Matplotlib's, 0.8."""
    tick_length: float | None = Field(None, gt=0.0)
    """Length of the major tick marks in pt; None keeps Matplotlib's, 3.5."""
    minor_tick_width: float | None = Field(None, gt=0.0)
    """Line width of the minor tick marks in pt; None keeps Matplotlib's, 0.6."""
    minor_tick_length: float | None = Field(None, gt=0.0)
    """Length of the minor tick marks in pt; None keeps Matplotlib's, 2."""
    panel_labels: PanelLabels | None = None
    """Letters on the panels, as journals ask for; None draws none."""
    layout: GridLayout = Field(default_factory=GridLayout)
    """The grid the panels are placed in."""
    axes: list[Axes] = Field(default_factory=list)
    """The panels, in the grid or as insets."""
