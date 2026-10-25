"""Artists: the things actually drawn inside an Axes.

Every artist carries a `kind` literal. The union below discriminates on it, so
loading a project file restores the concrete classes without a hand-written
dispatch table.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from figscribe.model.base import AnyFloat, Identified, StrictModel
from figscribe.model.data import ArrayRef, ColumnRef

Color = str
"""A Matplotlib color spec ("C0", "#ff0000", "tab:blue", ...).

Deliberately not modelled further: Matplotlib accepts many forms, and a stricter
type here would drift away from what the renderer actually supports. The
commands ask Matplotlib instead (`model/styles.py`).
"""


class ArtistBase(Identified):
    label: str | None = None
    """Legend entry; None means the artist is not listed."""
    visible: bool = True
    """False hides the plot but keeps it in the project."""
    zorder: float = 2.0
    """Drawing order: plots with a higher number are drawn on top."""
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    """Opacity from 0 (invisible) to 1 (opaque)."""
    axis: Literal["left", "right"] = "left"
    """Which y-axis to draw against."""


class LinePlot(ArtistBase):
    kind: Literal["line"] = "line"
    x: ColumnRef
    """Column of x values."""
    y: ColumnRef
    """Column of y values."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""
    linestyle: str = "-"
    """"-", "--", "-.", ":", or "none" for markers only."""
    linewidth: float = Field(1.5, gt=0.0)
    """Line width in pt."""
    marker: str | None = None
    """A Matplotlib marker such as "o", "s" or "^"; None draws none."""
    markersize: float = Field(4.0, gt=0.0)
    """Marker size in pt."""


class ScatterPlot(ArtistBase):
    kind: Literal["scatter"] = "scatter"
    x: ColumnRef
    """Column of x values."""
    y: ColumnRef
    """Column of y values."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""
    marker: str = "o"
    """A Matplotlib marker such as "o", "s" or "^"."""
    size: float = Field(20.0, gt=0.0)
    """Marker area in pt², as Matplotlib's scatter takes it."""
    edgecolor: Color | None = None
    """Color of the marker outlines; None follows the style."""


class ErrorbarPlot(ArtistBase):
    kind: Literal["errorbar"] = "errorbar"
    x: ColumnRef
    """Column of x values."""
    y: ColumnRef
    """Column of y values."""
    xerr: ColumnRef | None = None
    """Column of x errors, drawn as ± around each point; None draws none."""
    yerr: ColumnRef | None = None
    """Column of y errors, drawn as ± around each point; None draws none."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""
    linestyle: str = "none"
    """"none" draws only the points; "-" also joins them."""
    marker: str = "o"
    """A Matplotlib marker such as "o", "s" or "^"."""
    markersize: float = Field(4.0, gt=0.0)
    """Marker size in pt."""
    capsize: float = Field(2.0, ge=0.0)
    """Length of the caps at the ends of the error bars in pt; 0 for none."""
    elinewidth: float = Field(1.0, gt=0.0)
    """Line width of the error bars in pt."""


class Histogram(ArtistBase):
    kind: Literal["histogram"] = "histogram"
    values: ColumnRef
    """Column whose values are counted into bins."""
    bins: Annotated[int, Field(ge=1)] | list[float] = 20
    """A bin count, or explicit bin edges."""
    density: bool = False
    """True scales the bars to an area of 1; False shows counts."""
    histtype: Literal["bar", "step", "stepfilled"] = "bar"
    """"bar" fills each bin, "step" draws the outline, "stepfilled" a filled outline."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""


class Colorbar(StrictModel):
    visible: bool = True
    """False hides the color bar but keeps its settings."""
    label: str | None = None
    """LaTeX allowed."""


class ImagePlot(ArtistBase):
    kind: Literal["image"] = "image"
    data: ArrayRef
    """The 2-D array drawn, one pixel per value."""
    cmap: str = "viridis"
    """Name of a Matplotlib color map, e.g. viridis, magma or gray."""
    norm: Literal["linear", "log"] = "linear"
    """"log" spaces the colors logarithmically, for data over several decades."""
    vmin: float | None = None
    """Value at the bottom of the color map; None uses the data's smallest."""
    vmax: float | None = None
    """Value at the top of the color map; None uses the data's largest."""
    extent: tuple[float, float, float, float] | None = None
    """(left, right, bottom, top) in data coordinates; None lets Matplotlib pick."""
    origin: Literal["upper", "lower"] = "upper"
    """Where the first row goes: "upper" as in the file, "lower" as on a y axis."""
    aspect: Literal["auto", "equal"] = "auto"
    """"auto" fills the panel; "equal" keeps square pixels."""
    colorbar: Colorbar | None = None
    """A color bar beside the panel; None draws none."""


class ColorMesh(ArtistBase):
    kind: Literal["colormesh"] = "colormesh"
    c: ArrayRef
    """The 2-D array of cell values."""
    x: ColumnRef | None = None
    """Cell coordinates along x; None means index coordinates."""
    y: ColumnRef | None = None
    """Cell coordinates; None means index coordinates."""
    cmap: str = "viridis"
    """Name of a Matplotlib color map, e.g. viridis, magma or gray."""
    norm: Literal["linear", "log"] = "linear"
    """"log" spaces the colors logarithmically, for data over several decades."""
    vmin: float | None = None
    """Value at the bottom of the color map; None uses the data's smallest."""
    vmax: float | None = None
    """Value at the top of the color map; None uses the data's largest."""
    colorbar: Colorbar | None = None
    """A color bar beside the panel; None draws none."""


class PredefinedFit(StrictModel):
    kind: Literal["predefined"] = "predefined"
    name: Literal["linear", "polynomial", "gaussian", "lorentzian", "exponential"]
    """The function fitted; a polynomial also needs its degree."""
    degree: int | None = Field(None, ge=1)
    """Only for "polynomial"."""


class ExpressionFit(StrictModel):
    kind: Literal["expression"] = "expression"
    expression: str = Field(min_length=1)
    """A user-supplied expression in x and the named parameters."""
    parameters: list[str] = Field(min_length=1)
    """Names of the parameters in the expression, in the order the fit reports them."""


FitModel = Annotated[PredefinedFit | ExpressionFit, Field(discriminator="kind")]


class FitResult(StrictModel):
    """Outcome of a fit run, stored so that a reopened project shows it again."""

    parameters: dict[str, AnyFloat]
    """Not finite when the fit diverged; `converged` is then False."""
    uncertainties: dict[str, AnyFloat]
    """1-sigma, from the covariance matrix; inf when it cannot be estimated."""
    reduced_chi_square: AnyFloat | None = None
    """χ² per degree of freedom; None when the plot has no y errors to weigh the fit
    by."""
    converged: bool = True
    """False when curve_fit gave up; the parameters are then the start values."""


class FitCurve(ArtistBase):
    kind: Literal["fit"] = "fit"
    target: str = Field(min_length=1)
    """Artist.id of the line, scatter or errorbar plot this fit was run against."""
    model: FitModel
    """The function fitted."""
    initial_values: dict[str, float] = Field(default_factory=dict)
    """Start values by parameter name; missing ones are guessed from the data."""
    fixed: list[str] = Field(default_factory=list)
    """Parameters held at their start value instead of fitted."""
    parameter_bounds: dict[str, tuple[float | None, float | None]] = Field(
        default_factory=dict
    )
    """(lower, upper) by parameter name, None for an open end; a fitted value
    stays within them."""
    result: FitResult | None = None
    """The outcome of the last fit; None before the first."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""
    linestyle: str = "-"
    """"-", "--", "-." or ":"."""
    linewidth: float = Field(1.5, gt=0.0)
    """Line width in pt."""

    @field_validator("parameter_bounds")
    @classmethod
    def _ranges(cls, bounds):
        for name, (lower, upper) in bounds.items():
            if lower is not None and upper is not None and not lower < upper:
                raise ValueError(f"the lower bound of {name} is not below the upper")
        return bounds


class ResidualPlot(ArtistBase):
    """Residuals of a fit, drawn in an Axes of its own.

    Deliberately an artist in an explicit Axes rather than a flag on FitCurve:
    a residual panel is part of the layout, and the layout belongs in the model.
    Otherwise the renderer would have to invent an Axes and the code generator
    would have to reproduce that invention.
    """

    kind: Literal["residual"] = "residual"
    target: str = Field(min_length=1)
    """FitCurve.id whose residuals to draw."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""
    marker: str = "o"
    """A Matplotlib marker such as "o", "s" or "^"."""
    markersize: float = Field(4.0, gt=0.0)
    """Marker size in pt."""
    linestyle: str = "none"
    """"none" draws only the points; "-" also joins them."""


class Annotation(ArtistBase):
    kind: Literal["annotation"] = "annotation"
    text: str
    """LaTeX allowed."""
    position: tuple[float, float]
    """Where the text sits, in the coordinates `coords` names."""
    coords: Literal["data", "axes"] = "data"
    """"data" for data coordinates, "axes" for fractions of the panel from 0 to 1."""
    arrow_to: tuple[float, float] | None = None
    """Arrow tip in the same coordinate system; None means no arrow."""
    fontsize: float | None = Field(None, gt=0.0)
    """Font size in pt; None follows the figure."""
    color: Color | None = None
    """Color of the text and the arrow; None follows the style."""


Artist = Annotated[
    LinePlot
    | ScatterPlot
    | ErrorbarPlot
    | Histogram
    | ImagePlot
    | ColorMesh
    | FitCurve
    | ResidualPlot
    | Annotation,
    Field(discriminator="kind"),
]
