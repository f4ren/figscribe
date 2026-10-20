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
    limits: tuple[float, float] | None = None
    """None means autoscale. Adopting the current zoom writes a fixed pair here."""
    ticks: list[float] | None = None
    tick_labels: list[str] | None = None
    major_step: float | None = Field(None, gt=0.0)
    """Distance between major ticks; None lets Matplotlib choose. Explicit
    `ticks` win over it."""
    minor_ticks: bool = True
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
    location: str = "best"
    """A Matplotlib location string, used while `position` is None."""
    position: tuple[float, float] | None = None
    """Axes coordinates, set by dragging the legend; overrides `location`."""
    frame: bool = True
    ncols: int = Field(1, ge=1)
    fontsize: float | None = Field(None, gt=0.0)


class Inset(StrictModel):
    """Places an axes inside another panel instead of in the grid."""

    parent: str = Field(min_length=1)
    """Axes.id of the panel it sits in; that one must be in the grid."""
    bounds: tuple[float, float, float, float] = (0.55, 0.55, 0.4, 0.4)
    """(left, bottom, width, height) as fractions of the parent panel."""


class Axes(Identified):
    row: int = Field(0, ge=0)
    col: int = Field(0, ge=0)
    rowspan: int = Field(1, ge=1)
    colspan: int = Field(1, ge=1)

    title: str | None = None
    title_size: float | None = Field(None, gt=0.0)
    """Font size of the title in pt; None follows the figure."""
    x: AxisSpec = Field(default_factory=AxisSpec)
    y: AxisSpec = Field(default_factory=AxisSpec)
    y_right: AxisSpec | None = None
    """Second y-axis; artists opt into it via their `axis` field."""

    inset: Inset | None = None
    """Set for a panel inside another; row, col and the spans are then unused."""

    legend: Legend = Field(default_factory=Legend)
    grid: bool = False
    grid_axis: Literal["both", "x", "y"] = "both"
    """Which axis draws grid lines, when `grid` is on."""
    grid_which: Literal["major", "minor", "both"] = "major"
    """At which ticks grid lines are drawn, when `grid` is on."""
    grid_color: str | None = None
    """A Matplotlib color for the grid lines; None keeps the style's."""
    artists: list[Artist] = Field(default_factory=list)
