"""Artists: the things actually drawn inside an Axes.

Every artist carries a `kind` literal. The union below discriminates on it, so
loading a project file restores the concrete classes without a hand-written
dispatch table.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from figscribe.model.base import Identified, StrictModel
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
    zorder: float = 2.0
    alpha: float = Field(1.0, ge=0.0, le=1.0)
    axis: Literal["left", "right"] = "left"
    """Which y-axis to draw against."""


class LinePlot(ArtistBase):
    kind: Literal["line"] = "line"
    x: ColumnRef
    y: ColumnRef
    color: Color | None = None
    linestyle: str = "-"
    linewidth: float = Field(1.5, gt=0.0)
    marker: str | None = None
    markersize: float = Field(4.0, gt=0.0)


class ScatterPlot(ArtistBase):
    kind: Literal["scatter"] = "scatter"
    x: ColumnRef
    y: ColumnRef
    color: Color | None = None
    marker: str = "o"
    size: float = Field(20.0, gt=0.0)
    edgecolor: Color | None = None


class ErrorbarPlot(ArtistBase):
    kind: Literal["errorbar"] = "errorbar"
    x: ColumnRef
    y: ColumnRef
    xerr: ColumnRef | None = None
    yerr: ColumnRef | None = None
    color: Color | None = None
    linestyle: str = "none"
    marker: str = "o"
    markersize: float = Field(4.0, gt=0.0)
    capsize: float = Field(2.0, ge=0.0)
    elinewidth: float = Field(1.0, gt=0.0)


class Histogram(ArtistBase):
    kind: Literal["histogram"] = "histogram"
    values: ColumnRef
    bins: Annotated[int, Field(ge=1)] | list[float] = 20
    """A bin count, or explicit bin edges."""
    density: bool = False
    histtype: Literal["bar", "step", "stepfilled"] = "bar"
    color: Color | None = None


class Colorbar(StrictModel):
    visible: bool = True
    label: str | None = None
    """LaTeX allowed."""


class ImagePlot(ArtistBase):
    kind: Literal["image"] = "image"
    data: ArrayRef
    cmap: str = "viridis"
    norm: Literal["linear", "log"] = "linear"
    vmin: float | None = None
    vmax: float | None = None
    extent: tuple[float, float, float, float] | None = None
    """(left, right, bottom, top) in data coordinates; None lets Matplotlib pick."""
    origin: Literal["upper", "lower"] = "upper"
    """Where the first row goes: "upper" as in the file, "lower" as on a y axis."""
    aspect: Literal["auto", "equal"] = "auto"
    """"auto" fills the panel; "equal" keeps square pixels."""
    colorbar: Colorbar | None = None


class ColorMesh(ArtistBase):
    kind: Literal["colormesh"] = "colormesh"
    c: ArrayRef
    x: ColumnRef | None = None
    y: ColumnRef | None = None
    """Cell coordinates; None means index coordinates."""
    cmap: str = "viridis"
    norm: Literal["linear", "log"] = "linear"
    vmin: float | None = None
    vmax: float | None = None
    colorbar: Colorbar | None = None


class PredefinedFit(StrictModel):
    kind: Literal["predefined"] = "predefined"
    name: Literal["linear", "polynomial", "gaussian", "lorentzian", "exponential"]
    degree: int | None = Field(None, ge=1)
    """Only for "polynomial"."""


class ExpressionFit(StrictModel):
    kind: Literal["expression"] = "expression"
    expression: str = Field(min_length=1)
    """A user-supplied expression in x and the named parameters."""
    parameters: list[str] = Field(min_length=1)


FitModel = Annotated[PredefinedFit | ExpressionFit, Field(discriminator="kind")]


class FitResult(StrictModel):
    """Outcome of a fit run, stored so that a reopened project shows it again."""

    parameters: dict[str, float]
    uncertainties: dict[str, float]
    """1-sigma, from the covariance matrix."""
    reduced_chi_square: float | None = None
    converged: bool = True


class FitCurve(ArtistBase):
    kind: Literal["fit"] = "fit"
    target: str = Field(min_length=1)
    """Artist.id of the line, scatter or errorbar plot this fit was run against."""
    model: FitModel
    initial_values: dict[str, float] = Field(default_factory=dict)
    result: FitResult | None = None
    color: Color | None = None
    linestyle: str = "-"
    linewidth: float = Field(1.5, gt=0.0)


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
    marker: str = "o"
    markersize: float = Field(4.0, gt=0.0)
    linestyle: str = "none"


class Annotation(ArtistBase):
    kind: Literal["annotation"] = "annotation"
    text: str
    """LaTeX allowed."""
    position: tuple[float, float]
    coords: Literal["data", "axes"] = "data"
    arrow_to: tuple[float, float] | None = None
    """Arrow tip in the same coordinate system; None means no arrow."""
    fontsize: float | None = Field(None, gt=0.0)
    color: Color | None = None


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
