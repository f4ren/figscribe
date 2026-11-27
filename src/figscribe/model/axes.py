"""Axes and their parts."""

from __future__ import annotations

from itertools import pairwise
from typing import Literal

from pydantic import Field, field_validator

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
    """None means autoscale. Adopting the current zoom writes a fixed pair here;
    the first end may be the higher one, which turns the axis around."""
    inverted: bool = False
    """Draws the axis backwards, the highest value first (wavenumbers, binding
    energies), also while the range is automatic. A range typed highest end
    first turns the axis around as well, and this field does not undo that:
    to turn it back, set the field to False and give the range the lower end
    first."""
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
    labelpad: float | None = Field(None, ge=0.0)
    """Distance of the label from the numbers in pt; None follows the style.
    Where labels are aligned, a panel's own distance moves its label alone."""
    symlog_linthresh: float | None = Field(None, gt=0.0)
    """Only for scale "symlog"."""
    prefix: Literal["p", "n", "µ", "m", "k", "M", "G", "T"] | None = None
    """Shows the values with an SI prefix: "k" draws 225000 Hz as 225 and the
    unit as kHz. The data, limits, ticks and steps stay in the data's unit;
    None shows the values as they are."""

    number_format: Literal["auto", "fixed", "scientific"] = "auto"
    """How the tick numbers are written: "auto" as Matplotlib does, "fixed" with
    `decimals` places after the decimal mark, "scientific" each as a power of
    ten (2.5×10³) with `decimals` places in front of the ×. With a prefix, the
    prefixed value is formatted. Typed `tick_labels` are shown as typed."""
    decimals: int = Field(1, ge=0, le=10)
    """Places after the decimal mark for `number_format` "fixed" and
    "scientific"; "auto" ignores it."""

    breaks: list[tuple[float, float]] = Field(default_factory=list)
    """Stretches cut out of the axis, each (start, end) in the data's unit, in
    rising order and apart from each other: the axis is drawn with a narrow gap
    and break marks there, and nothing is shown within. For a measurement far
    from the rest. Only a linear x or left y axis can be broken; panels that
    share the axis share its breaks."""

    @field_validator("breaks")
    @classmethod
    def _apart(cls, breaks):
        for start, end in breaks:
            if not start < end:
                raise ValueError("a break needs a start below its end")
        for (_, end), (start, _) in pairwise(breaks):
            if not end < start:
                raise ValueError("breaks must be in rising order and apart")
        return breaks

    @field_validator("limits")
    @classmethod
    def _two_ends(cls, limits):
        if limits is not None and limits[0] == limits[1]:
            raise ValueError("a range needs two different ends")
        return limits


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
    grid_linewidth: float | None = Field(None, gt=0.0)
    """Width of the grid lines in pt; None keeps the style's, which is 0.8."""
    grid_linestyle: str | None = None
    """A Matplotlib line style for the grid lines, such as ":" or "--"; None
    keeps the style's solid line."""
    grid_minor_color: str | None = None
    """A color for the grid lines at the minor ticks; None keeps `grid_color`.
    Like the two fields below, it counts when `grid_which` is "minor" or
    "both"."""
    grid_minor_linewidth: float | None = Field(None, gt=0.0)
    """Width of the minor grid lines in pt; None makes them half as thick as
    the major ones when both are shown, and keeps `grid_linewidth` when only
    the minor ones are."""
    grid_minor_linestyle: str | None = None
    """A line style for the minor grid lines; None keeps `grid_linestyle`."""
    artists: list[Artist] = Field(default_factory=list)
    """The plots, fits and notes in the panel, drawn in this order."""
