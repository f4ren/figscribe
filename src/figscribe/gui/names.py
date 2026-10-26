"""What things are called on screen: plain words instead of model names."""

from __future__ import annotations

import math
from string import ascii_uppercase

from figscribe.model import Axes, Figure, FitCurve

KIND_NAMES = {
    "line": "Line",
    "scatter": "Points",
    "errorbar": "Error bar plot",
    "histogram": "Histogram",
    "image": "Image",
    "colormesh": "Color mesh",
    "fit": "Fit",
    "residual": "Residuals of the fit",
    "annotation": "Note",
}

FIELD_NAMES = {
    "x": "x",
    "y": "y",
    "xerr": "x error",
    "yerr": "y error",
    "c": "Values",
    "label": "Label",
    "visible": "Visible",
    "zorder": "Drawing order",
    "alpha": "Opacity",
    "axis": "y axis",
    "color": "Color",
    "edgecolor": "Edge color",
    "linestyle": "Line style",
    "linewidth": "Line width (pt)",
    "marker": "Marker",
    "markersize": "Marker size (pt)",
    "size": "Marker area (pt²)",
    "capsize": "Cap size (pt)",
    "elinewidth": "Error bar width (pt)",
    "histtype": "Style",
    "bins": "Bins (count, or edges)",
    "values": "Values",
    "density": "Normalize to density",
    "cmap": "Color map",
    "norm": "Scale",
    "vmin": "Lowest value",
    "vmax": "Highest value",
    "extent": "Extent",
    "text": "Text",
    "position": "Position",
    "coords": "Position in",
    "arrow_to": "Arrow to",
    "fontsize": "Font size (pt)",
    "target": "Fitted to",
    "name": "Name",
    "width_mm": "Width (mm)",
    "height_mm": "Height (mm)",
    "dpi": "Resolution (dpi)",
    "unit_format": "Units in labels",
    "stylesheet": "Style sheet",
    "font_size": "Font size (pt)",
    "title_size": "Title size (pt)",
    "label_size": "Label size (pt)",
    "tick_size": "Tick label size (pt)",
    "major_step": "Major tick every",
    "minor_divisions": "Minor divisions",
    "grid_axis": "Grid lines for",
    "grid_which": "Grid lines at",
    "grid_color": "Grid color",
    "layout": "Layout",
    "rows": "Rows",
    "cols": "Columns",
    "share_x": "Share x axis",
    "y_right": "Right y axis",
    "tick_direction": "Tick marks point",
    "ticks_all_sides": "Ticks on all sides",
    "prefix": "Show values in",
    "share_y": "Share y axis",
    "width_ratios": "Width ratios",
    "height_ratios": "Height ratios",
    "constrained_layout": "Automatic spacing",
    "hspace": "Vertical gap",
    "wspace": "Horizontal gap",
    "title": "Title",
    "row": "Row",
    "col": "Column",
    "rowspan": "Rows spanned",
    "colspan": "Columns spanned",
    "inset": "Inset",
    "parent": "Inside",
    "bounds": "Left, bottom, width, height",
    "grid": "Grid lines",
    "legend": "Legend",
    "unit": "Unit",
    "scale": "Scale",
    "limits": "Range",
    "ticks": "Ticks at",
    "tick_labels": "Tick labels",
    "minor_ticks": "Minor ticks",
    "symlog_linthresh": "Linear below",
    "location": "Location",
    "frame": "Frame",
    "ncols": "Columns",
    "colorbar": "Color bar",
    "path": "File",
    "sha256": "Fingerprint",
    "row_count": "Rows of data",
    "delimiter": "Separator",
    "decimal": "Decimal mark",
    "header_row": "Header line (first = 0)",
    "skip_rows": "Lines skipped",
    "comment": "Comment mark",
    "encoding": "Text encoding",
    "dataset": "Dataset",
    "array": "Array",
    "id": "Id",
    "kind": "Type",
    "format": "File type",
    "schema_version": "File format version",
    "figscribe_version": "Saved by",
    "created": "Created",
    "sources": "Data files",
    "figures": "Figures",
    "axes": "Panels",
    "artists": "Plots",
    "columns": "Columns",
    "source": "Data file",
    "column": "Column",
    "key": "Array",
    "data": "Data",
    "origin": "First row at",
    "aspect": "Pixel shape",
    "model": "Fit function",
    "degree": "Degree",
    "expression": "Formula",
    "parameters": "Parameters",
    "initial_values": "Start values",
    "fixed": "Held fixed",
    "parameter_bounds": "Parameter bounds",
    "fit_range": "Fit range",
    "extend_curve": "Curve over all the data",
    "outside_as_left_out": "Points outside the range like left out",
    "left_out": "Rows left out",
    "left_out_color": "Left-out color",
    "left_out_marker": "Left-out marker",
    "left_out_linestyle": "Left-out line style",
    "left_out_note": "Why left out",
    "result": "Result",
    "uncertainties": "Uncertainties (1σ)",
    "reduced_chi_square": "Reduced χ²",
    "converged": "Converged",
}


ENCODINGS = [
    ("UTF-8", "utf-8-sig"),
    ("Windows (cp1252)", "cp1252"),
    ("Latin-1 (ISO 8859-1)", "latin-1"),
]
"""The text encodings of CSV files, as offered for choice."""


def field_name(name: str) -> str:
    return FIELD_NAMES.get(name, name.replace("_", " ").capitalize())


def artist_name(artist) -> str:
    """The artist's legend label, or what it is."""
    if artist.label:
        return artist.label
    if isinstance(artist, FitCurve):
        model = artist.model
        if model.kind == "predefined":
            return f"{model.name.capitalize()} fit"
        return f"Fit: {model.expression}"
    if artist.kind == "annotation":
        first, *more = artist.text.split("\n")
        return f"Note: {first} …" if more else f"Note: {first}"
    return KIND_NAMES.get(artist.kind, artist.kind)


def panel_name(figure: Figure, axes: Axes) -> str:
    """ "Panel A", with where it sits when the figure has several."""
    name = f"Panel {_letter(figure, axes)}"
    if axes.inset is not None:
        host = next((a for a in figure.axes if a.id == axes.inset.parent), None)
        where = f"inset in {_letter(figure, host)}" if host else "inset"
        return f"{name} · {axes.title}" if axes.title else f"{name} · {where}"
    where = _position(figure, axes)
    if axes.title:
        return f"{name} · {axes.title}"
    return f"{name} · {where}" if where else name


def _letter(figure: Figure, axes: Axes) -> str:
    index = figure.axes.index(axes)
    return ascii_uppercase[index] if index < 26 else str(index + 1)


def _position(figure: Figure, axes: Axes) -> str:
    rows, cols = figure.layout.rows, figure.layout.cols
    if rows == 1 and cols == 1:
        return ""
    if cols == 1 and rows == 2:
        return "top" if axes.row == 0 else "bottom"
    if rows == 1 and cols == 2:
        return "left" if axes.col == 0 else "right"
    if cols == 1:
        return f"row {axes.row + 1}"
    if rows == 1:
        return f"column {axes.col + 1}"
    return f"row {axes.row + 1}, column {axes.col + 1}"


def size_text(figure: Figure) -> str:
    return f"{figure.width_mm:g} × {figure.height_mm:g} mm"


def with_error(value: float, error: float | None) -> str:
    """`value ± error`, both rounded to the error's two significant digits."""
    if error is None or not math.isfinite(error) or error <= 0:
        return f"{value:.4g}"
    digits = max(0, 1 - math.floor(math.log10(error)))
    if digits > 8 or abs(value) >= 1e6 or (value != 0 and abs(value) < 1e-4):
        return f"{value:.3e} ± {error:.2e}"
    return f"{value:.{digits}f} ± {error:.{digits}f}"
