"""Artists: the things actually drawn inside an Axes.

Every artist carries a `kind` literal. The union below discriminates on it, so
loading a project file restores the concrete classes without a hand-written
dispatch table.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator, model_validator

from figscribe.model.base import AnyFloat, Identified, StrictModel
from figscribe.model.data import ArrayRef, ColumnRef

LIKE_THE_PLOT = "same"
"""For the look of left-out points: as the plot itself has it."""

Color = str
"""A Matplotlib color spec ("C0", "#ff0000", "tab:blue", ...).

Deliberately not modelled further: Matplotlib accepts many forms, and a stricter
type here would drift away from what the renderer actually supports. The
commands ask Matplotlib instead (`model/styles.py`).
"""


def _lower_below_upper(ends: tuple[float, float]) -> tuple[float, float]:
    if not ends[0] < ends[1]:
        raise ValueError("the lower end of the range is not below the upper")
    return ends


Range = Annotated[tuple[float, float], AfterValidator(_lower_below_upper)]
"""(lower, upper), the lower below the upper."""


class Conversion(StrictModel):
    """Values shown in another unit, and counted from the start if asked:
    shown = (value − start) × factor, where the start is the column's
    smallest value with `from_start`, else 0 (decision 0041). Errors are
    scaled by the factor, never shifted."""

    factor: float = Field(gt=0.0)
    """What every value is multiplied by, e.g. 1/3600 to show s in h."""
    from_start: bool = False
    """Count from the column's smallest value, so that the values start at 0:
    hours since the start of a measurement rather than since 1970."""
    unit: str | None = None
    """The unit of the shown values, e.g. "h"; the axis takes it. None leaves
    the axis' unit as it is."""


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
    left_out: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    """Rows of the data, counted from 0, drawn apart and skipped by every fit of
    this plot; the data file stays as it is."""
    left_out_color: Color | None = None
    """Color of the left-out points; None draws them light grey."""
    left_out_marker: str | None = LIKE_THE_PLOT
    """Marker of the left-out points: "same" takes the plot's, None draws none."""
    left_out_linestyle: str = LIKE_THE_PLOT
    """How the line runs on through the left-out rows, in their color: "same"
    as the plot's, or "-", "--", "-.", ":", or "none" for a gap."""
    left_out_note: str | None = None
    """Why the rows are left out, e.g. "detector glitch"; written into the
    script. Finding outliers fills it in."""
    x_conversion: Conversion | None = None
    """The x values in another unit, counted from the start if asked; None
    shows them as in the file. x errors are scaled along."""
    y_conversion: Conversion | None = None
    """The y values in another unit, counted from the start if asked; None
    shows them as in the file. y errors and the band are scaled along."""
    x_range: Range | None = None
    """(lower, upper) of the shown x values: only the rows within it, both ends
    included, are drawn, fitted and counted; None uses every row."""


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
    left_out: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    """Rows of the data, counted from 0, drawn apart and skipped by every fit of
    this plot; the data file stays as it is."""
    left_out_color: Color | None = None
    """Color of the left-out points; None draws them light grey."""
    left_out_marker: str | None = LIKE_THE_PLOT
    """Marker of the left-out points: "same" takes the plot's, None draws none."""
    left_out_note: str | None = None
    """Why the rows are left out, e.g. "detector glitch"; written into the
    script. Finding outliers fills it in."""
    x_conversion: Conversion | None = None
    """The x values in another unit, counted from the start if asked; None
    shows them as in the file. x errors are scaled along."""
    y_conversion: Conversion | None = None
    """The y values in another unit, counted from the start if asked; None
    shows them as in the file. y errors and the band are scaled along."""
    x_range: Range | None = None
    """(lower, upper) of the shown x values: only the rows within it, both ends
    included, are drawn, fitted and counted; None uses every row."""


class ErrorBand(StrictModel):
    """The y errors as a shaded band around the line instead of as bars, for
    dense data where the bars would crowd each other."""

    color: Color | None = None
    """A Matplotlib color; None takes the plot's."""
    alpha: float = Field(0.25, ge=0.0, le=1.0)
    """Opacity of the band from 0 to 1, times the plot's own."""


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
    linewidth: float = Field(1.5, gt=0.0)
    """Width of the line joining the points in pt; the error bars have their
    own, elinewidth."""
    marker: str = "o"
    """A Matplotlib marker such as "o", "s" or "^"."""
    markersize: float = Field(4.0, gt=0.0)
    """Marker size in pt."""
    capsize: float = Field(2.0, ge=0.0)
    """Length of the caps at the ends of the error bars in pt; 0 for none."""
    elinewidth: float = Field(1.0, gt=0.0)
    """Line width of the error bars in pt."""
    band: ErrorBand | None = None
    """The y errors as a shaded band instead of bars; None draws bars. x
    errors stay bars."""
    left_out: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    """Rows of the data, counted from 0, drawn apart and skipped by every fit of
    this plot; the data file stays as it is."""
    left_out_color: Color | None = None
    """Color of the left-out points; None draws them light grey."""
    left_out_marker: str | None = LIKE_THE_PLOT
    """Marker of the left-out points: "same" takes the plot's, None draws none."""
    left_out_linestyle: str = LIKE_THE_PLOT
    """How the line runs on through the left-out rows, in their color: "same"
    as the plot's, or "-", "--", "-.", ":", or "none" for a gap."""
    left_out_note: str | None = None
    """Why the rows are left out, e.g. "detector glitch"; written into the
    script. Finding outliers fills it in."""
    x_conversion: Conversion | None = None
    """The x values in another unit, counted from the start if asked; None
    shows them as in the file. x errors are scaled along."""
    y_conversion: Conversion | None = None
    """The y values in another unit, counted from the start if asked; None
    shows them as in the file. y errors and the band are scaled along."""
    x_range: Range | None = None
    """(lower, upper) of the shown x values: only the rows within it, both ends
    included, are drawn, fitted and counted; None uses every row."""


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
    x_conversion: Conversion | None = None
    """The values in another unit, counted from the start if asked; None
    counts them as in the file."""
    x_range: Range | None = None
    """(lower, upper) of the shown values: only those are counted, and the
    bins of a bin count span it; None uses every value."""


class AllanDeviationPlot(ArtistBase):
    """The overlapping Allan deviation σ_y(τ) of an evenly sampled series
    against the averaging time τ: how stable a clock, laser or sensor is over
    time (decision 0036). Shown on log-log axes. Renderer and script compute
    it alike; the model stores only how."""

    kind: Literal["allan"] = "allan"
    values: ColumnRef
    """The series: fractional frequency values, or phase in s (see
    `data_type`), one per sample, without gaps."""
    data_type: Literal["frequency", "phase"] = "frequency"
    """"frequency": the values are fractional frequency y, without unit;
    "phase": they are phase (time error) x in s."""
    sample_interval: float = Field(1.0, gt=0.0)
    """Time between samples τ0 in s; unused when `time` is set."""
    time: ColumnRef | None = None
    """Column of the sample times in s, evenly spaced; its median step is τ0.
    None takes `sample_interval`."""
    taus: Literal["octave", "decade", "all"] = "octave"
    """Which τ = m·τ0 are shown: m = 1, 2, 4, 8, … ("octave"), 1, 2, 5, 10,
    … ("decade") or every m ("all"); up to half the series."""
    error_bars: bool = True
    """Show σ/√(N − 2m) as error bars, a simple estimate of the uncertainty."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""
    marker: str | None = "o"
    """A Matplotlib marker such as "o" or "s"; None draws none."""
    markersize: float = Field(4.0, gt=0.0)
    """Marker size in pt."""
    linestyle: str = "-"
    """"-", "--", "-.", ":", or "none" for points only."""
    linewidth: float = Field(1.5, gt=0.0)
    """Line width in pt."""
    x_conversion: Conversion | None = None
    """τ in another unit, e.g. h; only the factor counts here, τ starts at τ0
    whatever `from_start` says. None shows τ in s."""
    x_range: Range | None = None
    """(lower, upper) of the time since the first sample, in τ's shown unit:
    only the samples within it are used, τ0 stays; None uses every sample."""


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
    fit_range: tuple[float, float] | None = None
    """(lower, upper) of x: only the points within it are fitted; None fits all."""
    extend_curve: bool = False
    """Draw the fitted curve across all the data, not only the fit range."""
    outside_as_left_out: bool = False
    """Draw the plot's points outside the fit range like its left-out points;
    they are not left out of the plot."""
    result: FitResult | None = None
    """The outcome of the last fit; None before the first."""
    color: Color | None = None
    """A Matplotlib color; None takes the next color of the color cycle."""
    linestyle: str = "-"
    """"-", "--", "-." or ":"."""
    linewidth: float = Field(1.5, gt=0.0)
    """Line width in pt."""

    @field_validator("fit_range")
    @classmethod
    def _ordered(cls, fit_range):
        if fit_range is not None and not fit_range[0] < fit_range[1]:
            raise ValueError("the lower end of the fit range is not below the upper")
        return fit_range

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


class ReferenceLine(ArtistBase):
    """A line across the whole panel at one value: a threshold, a literature
    value, the start of a pulse."""

    kind: Literal["refline"] = "refline"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    """"vertical" draws the line at an x value, "horizontal" at a y value."""
    at: float
    """Where the line is drawn, in the data's unit of that axis."""
    color: Color = "gray"
    """A Matplotlib color."""
    linestyle: str = "--"
    """"-", "--", "-." or ":"."""
    linewidth: float = Field(1.0, gt=0.0)
    """Line width in pt."""


class ShadedSpan(ArtistBase):
    """A shaded band across the whole panel between two values: a region of
    interest, an excluded range, the time a field was on."""

    kind: Literal["span"] = "span"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    """"vertical" shades a range of x values, "horizontal" a range of y values."""
    start: float
    """One end of the range, in the data's unit of that axis."""
    end: float
    """The other end of the range."""
    color: Color = "gray"
    """A Matplotlib color."""
    alpha: float = Field(0.2, ge=0.0, le=1.0)
    """Opacity from 0 (invisible) to 1 (opaque); light, so the data shows through."""
    zorder: float = 0.5
    """Drawing order: plots with a higher number are drawn on top; below the
    grid lines and every plot by default."""

    @model_validator(mode="after")
    def _two_ends(self):
        if self.start == self.end:
            raise ValueError("a range needs two different ends")
        return self


Artist = Annotated[
    LinePlot
    | ScatterPlot
    | ErrorbarPlot
    | Histogram
    | AllanDeviationPlot
    | ImagePlot
    | ColorMesh
    | FitCurve
    | ResidualPlot
    | Annotation
    | ReferenceLine
    | ShadedSpan,
    Field(discriminator="kind"),
]
