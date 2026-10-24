"""Axes and their parts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from figscribe.model.artists import Artist
from figscribe.model.base import Identified, StrictModel


class AxisSpec(StrictModel):
    """One axis of an Axes: x, y, or the optional right-hand y."""

    label: str | None = None
    """LaTeX allowed, e.g. r"$\\lambda$"."""
    unit: str | None = None
    """Rendered alongside the label; kept separate so styles can decide the form."""
    scale: Literal["linear", "log", "symlog"] = "linear"
    """"linear", "log", or "symlog" (linear around zero, log beyond)."""
    limits: tuple[float, float] | None = None
    """None means autoscale. Adopting the current zoom writes a fixed pair here."""
    ticks: list[float] | None = None
    """Values of the major ticks; None lets Matplotlib or `major_step` place them."""
    tick_labels: list[str] | None = None
    """Text for each value in `ticks`; None shows the numbers."""
    major_step: float | None = Field(None, gt=0.0)
    """Distance between major ticks; None lets Matplotlib choose. Explicit
    `ticks` win over it."""
    minor_ticks: bool = True
    """False draws no minor ticks."""
    minor_divisions: int | None = Field(None, ge=2)
    """Into how many parts minor ticks divide a major interval; None lets
    Matplotlib choose."""
    label_size: float | None = Field(None, gt=0.0)
    """Font size of the axis label in pt; None follows the figure."""
    tick_size: float | None = Field(None, gt=0.0)
    """Font size of the tick labels in pt; None follows the figure."""
    symlog_linthresh: float | None = Field(None, gt=0.0)
    """Only for scale "symlog"."""
    prefix: Literal["p", "n", "µ", "m", "k", "M", "G", "T"] | None = None
    """Shows the values with an SI prefix: "k" draws 225000 Hz as 225 and the
    unit as kHz. The data, limits, ticks and steps stay in the data's unit;
    None shows the values as they are."""


class Legend(StrictModel):
    visible: bool = False
    """Whether the panel shows a legend of its labelled plots."""
    location: str = "best"
    """A Matplotlib location string, used while `position` is None."""
    position: tuple[float, float] | None = None
    """Axes coordinates, set by dragging the legend; overrides `location`."""
    frame: bool = True
    """Whether the legend has a box around it."""
    ncols: int = Field(1, ge=1)
    """Number of columns the entries are arranged in."""
    fontsize: float | None = Field(None, gt=0.0)
    """Font size in pt; None follows the figure."""


class Inset(StrictModel):
    """Places an axes inside another panel instead of in the grid."""

    parent: str = Field(min_length=1)
    """Axes.id of the panel it sits in; that one must be in the grid."""
    bounds: tuple[float, float, float, float] = (0.55, 0.55, 0.4, 0.4)
    """(left, bottom, width, height) as fractions of the parent panel."""


class Axes(Identified):
    row: int = Field(0, ge=0)
    """Grid row of the panel, from the top, starting at 0."""
    col: int = Field(0, ge=0)
    """Grid column of the panel, from the left, starting at 0."""
    rowspan: int = Field(1, ge=1)
    """How many grid rows the panel covers."""
    colspan: int = Field(1, ge=1)
    """How many grid columns the panel covers."""

    title: str | None = None
    """Text above the panel; LaTeX between $ signs. None for no title."""
    title_size: float | None = Field(None, gt=0.0)
    """Font size of the title in pt; None follows the figure."""
    x: AxisSpec = Field(default_factory=AxisSpec)
    """The x axis: label, unit, range, scale and ticks."""
    y: AxisSpec = Field(default_factory=AxisSpec)
    """The left y axis: label, unit, range, scale and ticks."""
    y_right: AxisSpec | None = None
    """Second y-axis; artists opt into it via their `axis` field."""

    inset: Inset | None = None
    """Set for a panel inside another; row, col and the spans are then unused."""

    legend: Legend = Field(default_factory=Legend)
    """The panel's legend; listed are plots with a label."""
    grid: bool = False
    """Whether grid lines are drawn behind the plots."""
    grid_axis: Literal["both", "x", "y"] = "both"
    """Which axis draws grid lines, when `grid` is on."""
    grid_which: Literal["major", "minor", "both"] = "major"
    """At which ticks grid lines are drawn, when `grid` is on."""
    grid_color: str | None = None
    """A Matplotlib color for the grid lines; None keeps the style's."""
    artists: list[Artist] = Field(default_factory=list)
    """The plots, fits and notes in the panel, drawn in this order."""
