"""The property panel: an editor for every field of the selected object.

The form is generated from the pydantic fields at run time, so a field added
to the model shows up here without GUI code. Fields are grouped into sections
(Data, Look, Legend, ...) with plain names; rarely needed ones sit folded
under "More". Each editor turns its input into
a SetField command; the model validates it, and a refused value is reported
and the editor shows the model's value again. Field constraints such as
`alpha` in [0, 1] are enforced by the model, not repeated here.
"""

from __future__ import annotations

import math
import pathlib
import re
import types
import typing
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Literal

import matplotlib.style
from matplotlib.colors import TABLEAU_COLORS, to_hex
from pydantic import BaseModel
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.commands import CommandError, Macro, SetField, find
from figscribe.fit import FitError, refit, residuals
from figscribe.gui import theme
from figscribe.gui.axisform import AXIS_TITLES, AxisForm, axis_summary
from figscribe.gui.document import AXIS_FIELDS, Document, axis_id, split_axis
from figscribe.gui.effect import without_effect
from figscribe.gui.markers import LIKE_THE_PLOT, marker_icon
from figscribe.gui.markers import MARKERS as ALL_MARKERS
from figscribe.gui.names import (
    ENCODINGS,
    KIND_NAMES,
    artist_name,
    field_name,
    panel_name,
    size_text,
    with_error,
)
from figscribe.gui.numbers import number, numbers, whole
from figscribe.gui.widgets import Section, TextBox, label
from figscribe.io.errors import DataError
from figscribe.io.refresh import read_differently, reading_options
from figscribe.model import (
    ArrayRef,
    Axes,
    AxisSpec,
    Colorbar,
    ColumnRef,
    ErrorBand,
    ExpressionFit,
    Figure,
    FitCurve,
    FitResult,
    PanelLabels,
    PredefinedFit,
    Project,
)
from figscribe.model.styles import style_problem
from figscribe.render.figure import style_context
from figscribe.render.ticks import PREFIXES

SKIPPED = {
    "id": "an identity, never edited",
    "kind": "fixed by the type of plot",
    "format": "fixed by the type of data file",
    "sources": "data files are added and removed in the outline",
    "figures": "figures are listed in the outline",
    "axes": "panels are added, moved and removed in the outline and the preview",
    "artists": "plots are added, moved and removed in the outline",
    "columns": "read from the file on import and listed in the outline",
    "model": "chosen in the fit dialog",
    "initial_values": "set in the fit dialog",
    "fit_range": "set in the fit dialog, since the fit is run again",
    "left_out": "points are left out by right-clicking them in the preview",
    "fixed": "set in the fit dialog, beside the start values",
    "parameter_bounds": "set in the fit dialog, beside the start values",
    "result": "computed by the fit and shown in the fit dialog",
}
"""Fields with no editor here, and why."""

READ_ONLY = {
    "path": "set by importing the file or locating it again",
    "sha256": "the file's fingerprint, taken on import",
    "row_count": "counted on import",
    "target": "the plot a fit or its residuals belong to, set when added",
    "parent": "the panel an inset sits in, set when it is added",
}
"""Shown, but changed only through their own actions, and which."""

SHOWN_WHEN_SET = {
    "inset": "made by adding a panel as an inset; its bounds are shown then",
}
"""Optional parts with no switch here, shown as a group once they exist."""

EDITED_ELSEWHERE: dict[type[BaseModel], str] = {
    Project: "never selected: figscribe writes its versions and date, and "
    "its data files and figures are edited in the outline",
    AxisSpec: "the axis form, opened by clicking an axis",
    ColumnRef: "a choice of the data's columns",
    ArrayRef: "a choice of the data files",
    PredefinedFit: "the fit dialog",
    ExpressionFit: "the fit dialog",
    FitResult: "the fit dialog, which shows the result",
}
"""Model classes whose fields the generated forms never show, and where they
are edited instead."""

COLOR_FIELDS = {"color", "edgecolor", "grid_color", "left_out_color"}

Path = tuple[str, ...]


@dataclass
class Spec:
    """How a field is edited, derived from its annotation."""

    kind: str
    optional: bool = False
    options: tuple = ()
    model: type[BaseModel] | None = None


OPTIONAL_PARTS: dict[str, type[BaseModel]] = {
    "y_right": AxisSpec,
    "colorbar": Colorbar,
    "panel_labels": PanelLabels,
    "band": ErrorBand,
}
"""Optional nested models switched on and off with a check box; when on, their
fields get a section of their own."""


def spec_for(name: str, annotation: Any) -> Spec | None:
    """The editor for a field, or None when the panel has none for it."""
    if name == "bins":
        return Spec("bins")
    if name in OPTIONAL_PARTS:
        return Spec("part", model=OPTIONAL_PARTS[name])
    optional = False
    args = typing.get_args(annotation)
    if _is_union(annotation) and type(None) in args:
        optional = True
        rest = [a for a in args if a is not type(None)]
        if len(rest) != 1:
            return None
        annotation = rest[0]
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if annotation is bool:
        return Spec("bool", optional)
    if origin is Literal:
        return Spec("choice", optional, options=args)
    if annotation is int:
        return Spec("int", optional)
    if annotation is float:
        return Spec("float", optional)
    if annotation is str:
        return Spec("color" if name in COLOR_FIELDS else "text", optional)
    if origin is tuple and args == (float,) * 4:
        return Spec("quad", optional)
    if origin is tuple and args == (float, float):
        return Spec("pair", optional)
    if origin is list and args == (float,):
        return Spec("floats", optional)
    if origin is list and args == (str,):
        return Spec("strings", optional)
    if annotation is ColumnRef:
        return Spec("column", optional)
    if annotation is ArrayRef:
        return Spec("array", optional)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return None if optional else Spec("model", model=annotation)
    return None


SECTIONS = {
    "x": "Data",
    "y": "Data",
    "xerr": "Data",
    "yerr": "Data",
    "values": "Data",
    "time": "Data",
    "data_type": "Data",
    "sample_interval": "Data",
    "taus": "Data",
    "bins": "Data",
    "c": "Data",
    "target": "Data",
    "name": "Size",
    "width_mm": "Size",
    "height_mm": "Size",
    "dpi": "Export",
    "unit_format": "Style",
    "stylesheet": "Style",
    "title": "Panel",
    "title_size": "Panel",
    "grid": "Panel",
    "grid_axis": "Panel",
    "grid_which": "Panel",
    "grid_color": "Panel",
    "grid_linewidth": "Panel",
    "grid_linestyle": "Panel",
    "font_size": "Style",
    "tick_direction": "Style",
    "ticks_all_sides": "Style",
    "frame_width": "Style",
    "tick_width": "Style",
    "tick_length": "Style",
    "minor_tick_width": "Style",
    "minor_tick_length": "Style",
    "panel_labels": "Style",
    "path": "File",
    "sha256": "File",
    "label": "Legend",
    "visible": "More",
    "zorder": "More",
    "axis": "Data",
    "orientation": "Data",
    "at": "Data",
    "start": "Data",
    "end": "Data",
    "y_right": "Panel",
    "data": "Data",
    "row": "Position",
    "col": "Position",
    "rowspan": "Position",
    "colspan": "Position",
}
"""Where a top-level field is shown; the rest goes to "Look" for plots and
"Reading" for data files. Nested models get a section of their own."""

LOOK = [
    "text",
    "color",
    "edgecolor",
    "marker",
    "markersize",
    "size",
    "linestyle",
    "linewidth",
    "capsize",
    "elinewidth",
    "band",
]
"""How the "Look" section starts; other fields follow in model order."""
SECTION_NAMES = {
    "x": "X axis",
    "y": "Y axis",
    "y_right": "Right y axis",
    "colorbar": "Color bar",
    "panel_labels": "Panel labels",
    "band": "Error band",
}
"""Titles of nested models' sections, where they differ from the field's name."""
LABEL_WIDTH = 116

ORDER = [
    "Data",
    "Size",
    "Panel",
    "Axes",
    "Position",
    "File",
    "Reading",
    "Look",
    "Style",
    "Legend",
    "Export",
]
BASIC = {
    "LinePlot": ("color", "marker", "linestyle", "linewidth", "label"),
    "ScatterPlot": ("color", "marker", "size", "edgecolor", "label"),
    "ErrorbarPlot": ("color", "marker", "linestyle", "capsize", "label"),
    "Histogram": ("color", "histtype", "density", "label"),
    "AllanDeviationPlot": ("color", "marker", "linestyle", "error_bars", "label"),
    "FitCurve": ("color", "linestyle", "linewidth", "extend_curve", "label"),
    "ResidualPlot": ("color", "marker", "markersize", "linestyle"),
    "Annotation": ("text", "color", "fontsize", "position", "arrow_to"),
    "ReferenceLine": ("color", "linestyle", "linewidth", "label"),
    "ShadedSpan": ("color", "alpha", "label"),
    "ImagePlot": ("cmap", "norm", "vmin", "vmax", "colorbar"),
    "ColorMesh": ("cmap", "norm", "vmin", "vmax", "colorbar"),
    "Figure": ("name", "width_mm", "height_mm", "font_size", "panel_labels"),
    "Axes": ("title", "grid", "y_right"),
}
"""The settings shown at first, per kind of object, apart from its data and
position: the most asked for, in the assistant's benchmark and otherwise.
The rest is under "More", folded, and found by the search."""
WHOLE = {"Data", "File", "Reading", "Position", "Axes", "Export", "More"}
"""Sections shown whole: what is plotted and where, not how it looks; and
the PNG resolution, kept apart from the size (decision 0006)."""

COLLAPSED = {"More", "Layout"}
"""Sections that start folded: rarely needed, but always there."""

PLACEHOLDERS = {
    "band.color": "the plot's",
    "left_out_note": "no reason given",
    "left_out_color": "light grey",
    "label": "not in the legend",
    "color": "automatic",
    "edgecolor": "automatic",
    "grid_color": "automatic",
    "grid_linewidth": "default",
    "frame_width": "default",
    "tick_width": "default",
    "tick_length": "default",
    "minor_tick_width": "default",
    "minor_tick_length": "default",
    "limits": "automatic",
    "ticks": "automatic",
    "tick_labels": "automatic",
    "fontsize": "default",
    "title": "none",
    "unit": "none",
    "stylesheet": "default",
    "vmin": "automatic",
    "vmax": "automatic",
    "hspace": "automatic",
    "font_size": "default",
    "title_size": "default",
    "label_size": "default",
    "tick_size": "default",
    "major_step": "automatic",
    "minor_divisions": "automatic",
    "wspace": "automatic",
    "arrow_to": "no arrow",
    "extent": "auto",
    "position": "by location",
    "delimiter": "spaces or tabs",
    "header_row": "no names",
    "comment": "none",
    "array": "the first",
    "width_ratios": "1",
    "height_ratios": "1",
}

TIPS = {
    "outside_as_left_out": "Draw the plot's points outside the fit range in its "
    "left-out color and marker; they are not left out of the plot.",
    "left_out_note": "Why the rows are left out, e.g. detector glitch; the script "
    "says it in a comment. Finding outliers in the fit dialog fills it in.",
    "left_out_color": "Color of the points left out (right-click a point in the "
    "preview); empty draws them light grey.",
    "left_out_marker": "Marker of the points left out: like the plot's, another, or "
    "none.",
    "left_out_linestyle": "How the line runs on through the rows left out, in "
    "their color: like the plot's, another style, or none for a gap.",
    "extend_curve": "Draw the fitted curve across all the data, not only over the "
    "points it was fitted to.",
    "name": "Shown in the contents list and used for the file names of exports.",
    "width_mm": "Width of the whole figure as printed; 85 mm is a typical "
    "single journal column, 175 mm a double one.",
    "height_mm": "Height of the whole figure as printed.",
    "dpi": "Resolution of PNG exports; PDF and SVG stay sharp at any size.",
    "unit_format": "How a unit is joined to an axis label.",
    "stylesheet": "A Matplotlib style sheet the figure starts from.",
    "font_size": "Base font size; labels, numbers and legend scale with it.",
    "tick_direction": "Whether tick marks point into the plot, out of it, or both.",
    "ticks_all_sides": "Tick marks also on the top and right edge of every "
    "panel; the numbers stay at the bottom and left.",
    "frame_width": "Line width of the frame around every panel; empty keeps "
    "the style's 0.8 pt.",
    "tick_width": "Line width of the numbered tick marks; empty keeps the "
    "style's 0.8 pt.",
    "tick_length": "Length of the numbered tick marks; empty keeps the style's 3.5 pt.",
    "minor_tick_width": "Line width of the minor tick marks; empty keeps the "
    "style's 0.6 pt.",
    "minor_tick_length": "Length of the minor tick marks; empty keeps the "
    "style's 2 pt.",
    "title": "Text above the panel; LaTeX between $ signs.",
    "title_size": "Font size of the title; empty follows the figure.",
    "y_right": "A second y axis on the right, for plots in another unit.",
    "grid": "Grid lines behind the plots.",
    "grid_axis": "Which axes get grid lines.",
    "grid_which": "Grid lines at the numbered ticks, the minor ticks, or both.",
    "grid_color": "Color of the grid lines, e.g. dimgray or #696969; empty "
    "keeps the style's light gray.",
    "grid_linewidth": "Width of the grid lines; empty keeps the style's 0.8 pt.",
    "grid_linestyle": "How the grid lines are drawn: solid, dashed, dotted or "
    "dash-dotted.",
    "row": "Grid row of the panel, counted from 1 at the top.",
    "col": "Grid column of the panel, counted from 1 at the left.",
    "rowspan": "How many grid rows the panel covers.",
    "colspan": "How many grid columns the panel covers.",
    "label": "Entry in the legend; empty keeps the plot out of it.",
    "zorder": "Plots with a higher number are drawn on top.",
    "alpha": "1 is opaque, 0 invisible.",
    "axis": "Which y axis the plot is drawn against.",
    "encoding": "How the file's letters are stored. Files from Windows programs "
    "are often cp1252; choose it if names like µA come out wrong.",
    "Colorbar.label": "Text beside the color bar; LaTeX between $ signs.",
    "visible": "Whether it is drawn; hidden, it keeps its settings.",
    "x": "The column plotted along x.",
    "y": "The column plotted along y.",
    "ColorMesh.x": "Column of the cell positions along x; empty numbers the cells.",
    "ColorMesh.y": "Column of the cell positions along y; empty numbers the cells.",
    "xerr": "The column of x errors, drawn as bars of ± that size; empty for none.",
    "yerr": "The column of y errors, drawn as bars of ± that size; empty for none.",
    "color": "A name such as blue or tab:orange, or a code such as #1f77b4; empty "
    "takes the next color of the cycle.",
    "Annotation.color": "Color of the text and the arrow; empty follows the style.",
    "ReferenceLine.color": "A name such as gray or tab:orange, or a code such as "
    "#1f77b4.",
    "ShadedSpan.color": "A name such as gray or tab:orange, or a code such as "
    "#1f77b4; the opacity keeps it light.",
    "ReferenceLine.orientation": "Vertical: at an x value, from bottom to top. "
    "Horizontal: at a y value, from left to right.",
    "ShadedSpan.orientation": "Vertical: a range of x values, shaded from bottom to "
    "top. Horizontal: a range of y values, shaded from left to right.",
    "at": "The value the line marks, in the unit of its axis.",
    "start": "One end of the shaded range, in the unit of its axis.",
    "end": "The other end of the shaded range.",
    "edgecolor": "Color of the marker outlines; empty follows the style.",
    "linestyle": "How the line is drawn: solid, dashed, dash-dotted, dotted, or none "
    "for points only.",
    "linewidth": "Line width in pt.",
    "ErrorbarPlot.linewidth": "Width of the line joining the points in pt; the "
    "error bars have their own width.",
    "marker": "The symbol drawn at each data point.",
    "markersize": "Size of the markers in pt.",
    "size": "Size of the markers in pt.",
    "capsize": "Length of the caps at the ends of the error bars in pt; 0 for none.",
    "elinewidth": "Line width of the error bars in pt.",
    "values": "The column whose values are counted.",
    "bins": "A number of bins of equal width, or their edges, e.g. 0, 1, 2.5.",
    "density": "Scale the bars to a total area of 1, to compare data sets of different"
    " size.",
    "histtype": "Filled bars, only their outline, or a filled outline.",
    "AllanDeviationPlot.values": "The series, one value per sample and without "
    "gaps: fractional frequency, or phase in s.",
    "data_type": "Fractional frequency (without unit), or phase, the time error in s.",
    "sample_interval": "Time between samples, τ0, in s; unused while a column of "
    "times is chosen.",
    "time": "The times of the samples in s, evenly spaced; their median step is "
    "the sample interval. Empty uses the interval typed in.",
    "taus": "Which averaging times τ = m·τ0 are shown: m = 1, 2, 4, 8 …, or "
    "1, 2, 5, 10 …, or every m.",
    "error_bars": "Show σ/√(N − 2m) as error bars, a simple estimate of the "
    "uncertainty.",
    "c": "The 2-D data whose values are shown as colors.",
    "data": "The 2-D data shown as an image, one pixel per value.",
    "cmap": "The colors the values are shown in, from lowest to highest.",
    "norm": "Linear spaces the colors evenly; logarithmic suits values over several "
    "decades.",
    "vmin": "The value shown in the lowest color; empty uses the smallest.",
    "vmax": "The value shown in the highest color; empty uses the largest.",
    "extent": "Where the image's edges lie in data coordinates: left, right, bottom, "
    "top. Empty numbers the pixels.",
    "origin": "Draw the first row of the data at the top, as in the file, or at the "
    "bottom, as on a y axis.",
    "aspect": "Fill the panel, or keep the pixels square.",
    "text": "The note's text; LaTeX between $ signs, e.g. $\\mu$.",
    "Annotation.position": "Where the note sits: x and y in the coordinates chosen "
    "below.",
    "coords": "Data coordinates, or fractions of the panel from 0 to 1.",
    "arrow_to": "Where an arrow from the note points, in the same coordinates; empty "
    "for no arrow.",
    "fontsize": "Font size in pt; empty follows the figure.",
    "location": "Where the legend goes, e.g. best, upper right, lower left.",
    "Legend.position": "Where the legend's lower left corner sits, as fractions of the"
    " panel; set by dragging the legend. Empty uses the location.",
    "frame": "A box around the legend.",
    "panel_labels": "Letters on the panels, (a), (b), (c), in reading order, as "
    "journals ask for.",
    "PanelLabels.style": "How the letters are written.",
    "band": "Shade the y errors as a band around the line instead of drawing bars, "
    "for dense data; x errors stay bars.",
    "ErrorBand.color": "Color of the band; empty takes the plot's.",
    "ErrorBand.alpha": "Opacity of the band, 1 opaque, 0 invisible; times the "
    "plot's own.",
    "bold": "Bold letters, as Nature and Science print them.",
    "placement": "Above and left of each panel's top left corner, or just within it.",
    "insets": "Give insets a letter too, right after the panel they sit in.",
    "ncols": "How many columns the legend's entries are arranged in.",
    "bounds": "Where the inset sits in its panel, as fractions: left, bottom, width, "
    "height.",
    "rows": "Rows of the panel grid.",
    "cols": "Columns of the panel grid.",
    "share_x": "Join the x axes of panels: one range for all, numbers only on the "
    "bottom row.",
    "share_y": "Join the y axes of panels: one range for all, numbers only in the left"
    " column.",
    "width_ratios": "How wide the columns are relative to each other, e.g. 2, 1; empty"
    " makes them equal.",
    "height_ratios": "How tall the rows are relative to each other, e.g. 3, 1; empty "
    "makes them equal.",
    "constrained_layout": "Let Matplotlib space the panels so that their labels do not"
    " overlap.",
    "hspace": "Space between rows, as a fraction of the average panel height; empty "
    "lets Matplotlib choose.",
    "wspace": "Space between columns, as a fraction of the average panel width; empty "
    "lets Matplotlib choose.",
    "delimiter": "What separates the values in a line; empty means spaces or tabs.",
    "decimal": "Whether the numbers are written 1.5 or 1,5.",
    "header_row": "The line with the column names, counted from 1; empty for a file "
    "without names.",
    "skip_rows": "Lines between the names and the numbers, such as a line of units.",
    "comment": "Lines starting with this are ignored; empty for none.",
    "dataset": "Where the data lies inside the HDF5 file, e.g. /run3/voltage.",
    "array": "Which array of the .npz archive to plot.",
}
"""Explanations shown when the mouse rests on a field, by field name, or by
"Class.field" where the same name means something else there."""


SHARED = (
    "color",
    "marker",
    "markersize",
    "size",
    "edgecolor",
    "linestyle",
    "linewidth",
    "capsize",
    "elinewidth",
    "alpha",
    "visible",
)
"""What several plots chosen together can have set at once, where every one
of them has it."""


class _Several:
    """The value of a setting the plots chosen together do not agree on."""

    def __repr__(self) -> str:
        return "several"


SEVERAL = _Several()


def _shared_spec(objs: list[BaseModel], name: str) -> Spec | None:
    """The editor for `name` on all of `objs`, if each has it and of one
    kind; None may be chosen only if every one of them takes it."""
    specs = []
    for obj in objs:
        field = type(obj).model_fields.get(name)
        if field is None:
            return None
        specs.append(spec_for(name, field.annotation))
    if any(spec is None or spec.kind != specs[0].kind for spec in specs):
        return None
    return next((spec for spec in specs if not spec.optional), specs[0])


def _common(objs: list[BaseModel], path: Path) -> Any:
    """The value at `path` the objects agree on, or SEVERAL."""
    values = [_get(obj, path) for obj in objs]
    return values[0] if all(v == values[0] for v in values) else SEVERAL


def _set_on_all(objs: list[BaseModel], path: Path, value: Any) -> Macro:
    steps = [SetField(obj.id, path, value) for obj in objs if _get(obj, path) != value]
    return Macro(f"Change {len(objs)} plots", steps)


def _basic_first(groups: dict[str, list[str]], basic: tuple[str, ...] | None):
    """Move the fields that are not `basic` from their sections to "More",
    in their order, before what "More" has; drop the sections left empty."""
    if basic is None:
        return
    moved = []
    for title in list(groups):
        if title in WHOLE:
            continue
        moved += [n for n in groups[title] if n not in basic]
        groups[title] = [n for n in groups[title] if n in basic]
        if not groups[title]:
            del groups[title]
    if moved:
        groups["More"] = [*moved, *groups.get("More", [])]


FILTER_DELAY_MS = 150
"""How long the search waits after a key before it filters, so that typing
a word builds the form once."""


def _row_text(form: QFormLayout, row: int) -> str:
    """What a search looks in for a row: its caption, and the tooltips of
    the caption and the field, lower case."""
    parts = []
    for role in (
        QFormLayout.ItemRole.LabelRole,
        QFormLayout.ItemRole.FieldRole,
        QFormLayout.ItemRole.SpanningRole,
    ):
        item = form.itemAt(row, role)
        widget = item.widget() if item is not None else None
        if widget is None:
            continue
        if role != QFormLayout.ItemRole.FieldRole:  # a field's text is its value
            parts.append(getattr(widget, "text", lambda: "")())
        parts.append(widget.toolTip())
    return " ".join(p for p in parts if isinstance(p, str)).lower()


def tip_for(owner: type[BaseModel], name: str) -> str | None:
    return TIPS.get(f"{owner.__name__}.{name}", TIPS.get(name))


GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "lambda_": "λ",
    "mu": "μ",
    "nu": "ν",
    "omega": "ω",
    "phi": "φ",
    "sigma": "σ",
    "tau": "τ",
    "theta": "θ",
}


class PropertyPanel(QScrollArea):
    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("properties")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(300)
        self.pick_color: Callable[[str | None], str | None] = self._pick_color
        """Asks for a color; replaced in tests."""
        self.recent_colors: list[str] = []
        """Colors set lately, newest first; every color field offers them."""
        self.drawn_color: Callable[[str], str | None] = lambda oid: None
        """The color a plot is drawn in now; the window asks the preview."""
        self.choose_file: Callable[[str, str], pathlib.Path | None] = self._choose_file
        """Asks for a file, by dialog title and name pattern; replaced in tests."""
        self.editors: dict[Path, Editor] = {}
        self.sections: dict[str, Section] = {}
        self._shown: tuple | None = None
        self._fit_result = None
        self.axis_form: AxisForm | None = None
        self.axis_range: Callable[[str], tuple[float, float] | None] = lambda _: None
        """The range an axis shows right now; the window asks the preview."""
        self.edit_fit: Callable[[str], None] = lambda fit_id: None
        """Opens the fit dialog on a fit that is there; the window does."""
        self._folded = {title: True for title in COLLAPSED}
        self.search = QLineEdit()
        """Filters the fields by name and tooltip; the window puts it above
        the panel, where it stays when the form is built anew."""
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Find a setting, e.g. tick or font")
        self.search.setClearButtonEnabled(True)
        self._filtering = QTimer(self)
        self._filtering.setSingleShot(True)
        self._filtering.setInterval(FILTER_DELAY_MS)
        self._filtering.timeout.connect(self.rebuild)
        self.search.textChanged.connect(lambda _: self._filtering.start())
        QShortcut(
            QKeySequence(Qt.Key.Key_Escape),
            self.search,
            self.search.clear,
            context=Qt.ShortcutContext.WidgetShortcut,
        )
        self.matches = 0
        """How many fields the search shows; all of them without a search."""
        self._searched = False
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.selection_changed.connect(self.rebuild)
        document.changed.connect(self.refresh)
        self.rebuild()

    @property
    def error(self) -> str:
        return self._error.text()

    def rebuild(self, *_: object) -> None:
        """Build the form for the selected object."""
        for title, section in self.sections.items():
            # What the search opened is not what the user unfolded.
            if isinstance(section.header, QToolButton) and not self._searched:
                self._folded[title] = not section.expanded
        self.editors = {}
        self._captions: dict[Path, tuple[QLabel, str | None]] = {}
        self.sections = {}
        self.axis_links: dict[str, QPushButton] = {}
        body = QWidget()
        body.setObjectName("sidePanel")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.axis_form = None
        axis = split_axis(self.document.selected)
        obj = self._selected_object()
        several = self._several()
        if several:
            self._shown = self._shape_of(obj)
            layout.addWidget(self._several_header(several))
        elif obj is None:
            self._shown = None
            hint = label(
                "Select a figure, panel, plot or data file to edit it.", "hint"
            )
            hint.setContentsMargins(16, 16, 16, 16)
            layout.addWidget(hint)
        else:
            self._shown = self._shape_of(obj)
            layout.addWidget(self._header(obj))
        self._error = label("", "error")
        self._error.setContentsMargins(16, 8, 16, 0)
        self._error.hide()
        layout.addWidget(self._error)
        if several:
            self._fill_several(several, layout)
        elif axis is not None and obj is not None:
            oid = self.document.selected
            self.axis_form = AxisForm(
                self, axis[0], axis[1], layout, lambda: self.axis_range(oid)
            )
            self.axis_form.show(obj)
        elif obj is not None:
            self._fill(obj, layout)
            self._grey_out(obj)
        self._no_match = label("", "hint")
        self._no_match.setContentsMargins(16, 16, 16, 16)
        self._no_match.hide()
        layout.addWidget(self._no_match)
        self._filter()
        layout.addStretch(1)
        old = self.takeWidget()
        if old is not None:
            # One of its editors may be what asked for this, still handling
            # the click; setWidget() alone would delete it under Qt's feet.
            old.hide()
            old.deleteLater()
        self.setWidget(body)

    def refresh(self) -> None:
        """Show the model's current values; rebuild if the object changed."""
        obj = self._selected_object()
        if obj is None or self._shown != self._shape_of(obj):
            self.rebuild()
            return
        several = self._several()
        if several:
            for path, editor in self.editors.items():
                editor.show(_common(several, path))
            self._filter()
            return
        if isinstance(obj, FitCurve) and obj.result != self._fit_result:
            self.rebuild()
            return
        self._update_header(obj)
        if self.axis_form is not None:
            self.axis_form.show(obj)
        for path, editor in self.editors.items():
            editor.show(_get(obj, path))
        self._grey_out(obj)
        self._filter()

    def _filter(self) -> None:
        """Hide the fields the search does not find, and the sections left
        empty; open a folded section that has one."""
        self._filtering.stop()
        words = self.search.text().lower().split()
        self._searched = bool(words)
        self.matches = 0
        for title, section in self.sections.items():
            form = section.body.layout()
            if not isinstance(form, QFormLayout):
                continue
            titled = all(w in title.lower() for w in words)
            shown = 0
            for row in range(form.rowCount()):
                if not form.isRowVisible(row):
                    continue  # hidden by the form itself, for another setting
                if titled or all(w in _row_text(form, row) for w in words):
                    shown += 1
                else:
                    form.setRowVisible(row, False)
            self.matches += shown
            if not words:
                continue
            section.setVisible(shown > 0)
            if shown and isinstance(section.header, QToolButton):
                section.header.setChecked(True)
        if words and not self.matches and self.sections:
            self._no_match.setText(f"No setting here matches “{self.search.text()}”.")
            self._no_match.show()

    def reveal(self, caption: str, title: str) -> None:
        """Show the field `caption` of section `title`, as `settings` names
        it: without a search, its section open, scrolled to and focused."""
        if self.search.text():
            self.search.clear()
            self.rebuild()
        for text, where, widget in self.settings():
            if (text, where) == (caption, title):
                section = self.sections[title]
                if isinstance(section.header, QToolButton):
                    section.header.setChecked(True)
                self.ensureWidgetVisible(widget)
                widget.setFocus(Qt.FocusReason.ShortcutFocusReason)
                return

    def settings(self) -> list[tuple[str, str, QWidget]]:
        """(caption, section, field widget) of every field of the selection,
        for the command palette."""
        found = []
        for title, section in self.sections.items():
            form = section.body.layout()
            if not isinstance(form, QFormLayout):
                continue
            for row in range(form.rowCount()):
                caption = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if caption is None or field is None or field.widget() is None:
                    continue
                text = getattr(caption.widget(), "text", lambda: "")()
                if text and field.widget().isEnabled():
                    found.append((text, title, field.widget()))
        return found

    def _grey_out(self, obj: BaseModel) -> None:
        """Grey out the fields that do nothing now, and say why."""
        for path, editor in self.editors.items():
            caption, tip = self._captions[path]
            why = without_effect(obj, path, self.document.project)
            told = "\n\n".join(t for t in (why, tip) if t)
            for widget in (caption, editor.widget):
                widget.setEnabled(why is None)
                widget.setToolTip(told)

    def commit(self, oid: str, path: Path, value: Any) -> None:
        """Set the field at `path` of object `oid` to `value`.

        Ignored unless `oid` is still the selected object: an editor torn down
        by a selection change can still report its last input.
        """
        if oid != self.document.selected or value is SEVERAL:
            return
        try:
            several = self._several()
            if several:
                self.document.push(_set_on_all(several, path, value))
                self._error.hide()
                return
            obj = find(self.document.project, oid)
            if _get(obj, path) == value:
                return
            self.document.push(self._command(obj, path, value))
        except (CommandError, DataError) as exc:
            self.report(str(exc))
            self.refresh()
        else:
            self._error.hide()

    def _command(self, obj: BaseModel, path: Path, value: Any):
        """The change for one field; a right y axis comes and goes with the
        plots drawn against it, and a data file is read again when how it is
        read changes."""
        if len(path) == 1 and path[0] in reading_options(obj):
            return read_differently(
                self.document.project, obj.id, path[0], value, self.document.base_dir
            )
        if path == ("panel_labels",):
            if value:
                return Macro(
                    "Letter the panels", [SetField(obj.id, path, PanelLabels())]
                )
            return Macro("Remove the panel labels", [SetField(obj.id, path, None)])
        if path == ("band",):
            if value:
                return Macro("Shade the errors", [SetField(obj.id, path, ErrorBand())])
            return Macro("Draw the errors as bars", [SetField(obj.id, path, None)])
        if path == ("colorbar",):
            if value:
                return Macro("Show a color bar", [SetField(obj.id, path, Colorbar())])
            return Macro("Remove the color bar", [SetField(obj.id, path, None)])
        if path == ("y_right",):
            if value:
                return Macro(
                    "Add the right y axis", [SetField(obj.id, path, AxisSpec())]
                )
            back = [
                SetField(a.id, ("axis",), "left")
                for a in obj.artists
                if a.axis == "right"
            ]
            return Macro(
                "Remove the right y axis", [*back, SetField(obj.id, path, None)]
            )
        if path == ("axis",) and value == "right":
            axes = _axes_of(self.document.project, obj.id)
            if axes is not None and axes.y_right is None:
                return Macro(
                    "Draw against a new right y axis",
                    [
                        SetField(axes.id, ("y_right",), AxisSpec()),
                        SetField(obj.id, path, value),
                    ],
                )
        return SetField(obj.id, path, value)

    def report(self, message: str) -> None:
        self._error.setText(message)
        self._error.show()

    def clear_report(self) -> None:
        self._error.hide()

    def _shape_of(self, obj: BaseModel) -> tuple:
        oid = self.document.selected
        if len(self.document.selection) > 1:
            return ("several", tuple(self.document.selection))
        return ("axis", oid) if split_axis(oid) else _shape(obj)

    def _several(self) -> list[BaseModel]:
        """The plots selected together; empty while one object or none is."""
        oids = self.document.selection
        if len(oids) < 2:
            return []
        try:
            return [find(self.document.project, oid) for oid in oids]
        except CommandError:
            return []

    def _several_header(self, objs: list[BaseModel]) -> QWidget:
        box = self._header(objs[-1])
        names = [artist_name(obj) for obj in objs]
        self._kicker.setText(f"{len(objs)} PLOTS")
        self._title.setText(", ".join(names))
        self._title.setWordWrap(True)
        return box

    def _fill_several(self, objs: list[BaseModel], layout: QVBoxLayout) -> None:
        """The settings the plots share, each showing their value if they
        agree; a change sets it on all of them, as one undo step."""
        form = self._section("Together", layout)
        for name in SHARED:
            spec = _shared_spec(objs, name)
            if spec is None:
                continue
            path = (name,)
            editor = make_editor(spec, path, self)
            value = _common(objs, path)
            editor.show(value)
            line = getattr(editor, "line", None)
            if value is SEVERAL and isinstance(line, QLineEdit):
                line.setPlaceholderText("several values")
            self.editors[path] = editor
            caption = _form_label(name)
            tip = tip_for(type(objs[-1]), name)
            self._captions[path] = (caption, tip)
            if tip is not None:
                caption.setToolTip(tip)
                editor.widget.setToolTip(tip)
            form.addRow(caption, editor.widget)
        if not self.editors:
            form.addRow(label("These plots share no setting.", "hint"))

    # --- layout ---------------------------------------------------------------

    def _header(self, obj: BaseModel) -> QWidget:
        box = QWidget()
        box.setObjectName("section")
        column = QVBoxLayout(box)
        column.setContentsMargins(16, 16, 16, 14)
        column.setSpacing(2)
        self._kicker = label("", "panelKicker")
        self._title = label("", "panelTitle")
        column.addWidget(self._kicker)
        column.addWidget(self._title)
        self._update_header(obj)
        return box

    def _update_header(self, obj: BaseModel) -> None:
        axis = split_axis(self.document.selected)
        if axis is not None:
            axes = find(self.document.project, axis[0])
            panel = _describe(axes, self.document)[1]
            kicker, title = f"{AXIS_TITLES[axis[1]]} · {panel}", axis_summary(obj)
        else:
            kicker, title = _describe(obj, self.document)
        self._kicker.setText(kicker.upper())
        self._title.setText(title)

    def _fill(self, obj: BaseModel, layout: QVBoxLayout) -> None:
        fallback = "Reading" if hasattr(obj, "format") else "Look"
        groups: dict[str, list[str]] = {}
        nested: list[str] = []
        inset = isinstance(obj, Axes) and obj.inset is not None
        for name, field in type(obj).model_fields.items():
            if name in SKIPPED:
                continue
            if name in SHOWN_WHEN_SET:
                if getattr(obj, name) is not None:
                    nested.append(name)
                continue
            if (
                name in OPTIONAL_PARTS
                and getattr(obj, name) is not None
                and not (isinstance(obj, Axes) and name in AXIS_FIELDS)
            ):
                nested.append(name)
            if inset and SECTIONS.get(name) == "Position":
                continue  # an inset is placed by its bounds, not in the grid
            if isinstance(obj, Axes) and name in ("x", "y"):
                continue  # each axis has its own form, linked from "Axes"
            spec = spec_for(name, field.annotation)
            if spec is not None and spec.kind == "model":
                nested.append(name)
                continue
            if spec is None and name not in READ_ONLY:
                continue
            groups.setdefault(SECTIONS.get(name, fallback), []).append(name)
        if "Look" in groups:
            groups["Look"].sort(key=lambda n: LOOK.index(n) if n in LOOK else 99)
        _basic_first(groups, BASIC.get(type(obj).__name__))
        titles = {_section_name(n): n for n in nested}
        if isinstance(obj, Axes):
            groups.setdefault("Axes", [])
        order = [t for t in ORDER if t in groups]
        order += [t for t in titles if t not in groups]
        order += [t for t in groups if t not in order]
        for title in order:
            form = self._section(title, layout)
            for name in groups.get(title, []):
                self._row(form, obj, (name,))
            if title in titles:
                name = titles[title]
                self._nested(form, getattr(obj, name), (name,))
            if title == "Axes":
                self._axis_links(form, obj)
            if title == "Data" and isinstance(obj, FitCurve):
                layout.addWidget(self._fit_card(obj))
        self._fit_result = getattr(obj, "result", None)

    def _section(self, title: str, layout: QVBoxLayout) -> QFormLayout:
        collapsible = title in COLLAPSED
        section = Section(
            title, collapsible, expanded=not self._folded.get(title, False)
        )
        self.sections[title] = section
        form = QFormLayout(section.body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addWidget(section)
        return form

    def _nested(self, form: QFormLayout, model: BaseModel, prefix: Path) -> None:
        for name, field in type(model).model_fields.items():
            if name in SKIPPED:
                continue
            spec = spec_for(name, field.annotation)
            if spec is not None and spec.kind == "model":
                heading = label(_section_name(name), "sectionTitle")
                form.addRow(heading)
                self._nested(form, getattr(model, name), (*prefix, name))
                continue
            self._row(form, model, (*prefix, name))

    def _row(self, form: QFormLayout, obj: BaseModel, path: Path) -> None:
        name = path[-1]
        value = getattr(obj, name)
        if name in READ_ONLY:
            text = _read_only_text(name, value, self.document)
            shown = label(text, "value")
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            shown.setToolTip(str(value))
            form.addRow(_form_label(name), shown)
            return
        spec = spec_for(name, type(obj).model_fields[name].annotation)
        if spec is None:
            return
        editor = make_editor(spec, path, self)
        editor.show(value)
        self.editors[path] = editor
        caption = _form_label(name)
        tip = tip_for(type(obj), name)
        self._captions[path] = (caption, tip)
        if tip is not None:
            caption.setToolTip(tip)
            editor.widget.setToolTip(tip)
        form.addRow(caption, editor.widget)

    def _axis_links(self, form: QFormLayout, axes: Axes) -> None:
        """One line per axis; clicking it opens the axis's own form."""
        for field in AXIS_FIELDS:
            spec = getattr(axes, field)
            if spec is None:
                continue
            text = f"{AXIS_TITLES[field].capitalize()}\n{axis_summary(spec)}  ›"
            link = QPushButton(text)
            link.setObjectName("axisLink")
            link.setToolTip(f"Range, ticks and label of the {AXIS_TITLES[field]}")
            link.clicked.connect(
                lambda _=False, f=field: self.document.select(axis_id(axes.id, f))
            )
            self.axis_links[field] = link
            form.addRow(link)

    def _fit_card(self, fit: FitCurve) -> QWidget:
        holder = QWidget()
        holder.setObjectName("section")
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.addWidget(label("Result", "sectionTitle"))
        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(16)
        lines = _result_lines(fit, self._residuals(fit))
        if not lines:
            grid.addWidget(label("Not fitted yet.", "hint"), 0, 0)
        for row, (name, value) in enumerate(lines):
            grid.addWidget(label(GREEK.get(name, name), "value"), row, 0)
            shown = label(value, "value")
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(shown, row, 1)
        if fit.result is not None and not fit.result.converged:
            warning = label("The fit did not converge.", "error")
            grid.addWidget(warning, len(lines), 0, 1, 2)
        grid.setColumnStretch(1, 1)
        outer.addWidget(card)
        copy = QPushButton("Copy the result")
        copy.setObjectName("link")
        copy.setToolTip("As text: parameters, χ²ᵣ and residuals")
        copy.setEnabled(bool(lines))
        copy.clicked.connect(lambda: self._copy_result(fit))
        self.copy_result_button = copy
        outer.addWidget(copy, 0, Qt.AlignmentFlag.AlignLeft)
        edit = QPushButton("Change the fit…")
        edit.setObjectName("link")
        edit.setToolTip("Model, start values, held parameters and bounds")
        edit.clicked.connect(lambda: self.edit_fit(fit.id))
        self.edit_fit_button = edit
        again = QPushButton("Fit again with the current data")
        again.setObjectName("link")
        again.clicked.connect(lambda: self.fit_again(fit.id))
        self.fit_again_button = again
        outer.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(again, 0, Qt.AlignmentFlag.AlignLeft)
        return holder

    def _residuals(self, fit: FitCurve):
        try:
            return residuals(self.document.project, fit.id, self.document.data)
        except (FitError, CommandError, DataError):
            return None  # the data cannot be read; the preview says why

    def _copy_result(self, fit: FitCurve) -> None:
        target = find(self.document.project, fit.target)
        name = (
            f"{fit.model.name.capitalize()} fit"
            if fit.model.kind == "predefined"
            else f"Fit of {fit.model.expression}"
        )
        head = f"{fit.label}: " if fit.label else ""
        lines = [f"{head}{name} to {artist_name(target)}"]
        lines += [f"{n} = {v}" for n, v in _result_lines(fit, self._residuals(fit))]
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(lines) + "\n")

    def fit_again(self, fit_id: str) -> None:
        """Run the fit again, e.g. after its data or start values changed."""
        try:
            self.document.push(refit(self.document.project, fit_id, self.document.data))
        except (FitError, CommandError, DataError) as exc:
            self.report(str(exc))

    def ask_marker(self, current: str | None) -> str | None:
        """Asks for a marker of one's own; None if cancelled. Replaced in tests."""
        text, ok = QInputDialog.getText(
            self,
            "Marker",
            "Any Matplotlib marker, e.g. $\\alpha$ for a Greek letter:",
            text=current or "",
        )
        return text.strip() or None if ok else None

    def _selected_object(self) -> BaseModel | None:
        oid = self.document.selected
        if oid is None:
            return None
        axis = split_axis(oid)
        try:
            obj = find(self.document.project, axis[0] if axis else oid)
        except CommandError:
            return None
        return getattr(obj, axis[1]) if axis else obj

    def remember_color(self, color: str) -> None:
        self.recent_colors = [color, *(c for c in self.recent_colors if c != color)]
        del self.recent_colors[RECENT_COLORS:]

    def _choose_file(self, title: str, pattern: str) -> pathlib.Path | None:
        chosen, _ = QFileDialog.getOpenFileName(self, title, "", pattern)
        return pathlib.Path(chosen) if chosen else None

    def _pick_color(self, current: str | None) -> str | None:
        start = QColor(theme.plot_color(current, 0))
        color = QColorDialog.getColor(start, self, "Color")
        return color.name() if color.isValid() else None


# --- editors -----------------------------------------------------------------


class Editor:
    """Shows one field's value and commits the user's input."""

    widget: QWidget

    def __init__(self, spec: Spec, path: Path, panel: PropertyPanel):
        self.spec = spec
        self.path = path
        self.panel = panel
        self.oid = panel.document.selected

    def show(self, value: Any) -> None:
        raise NotImplementedError

    def commit(self, value: Any) -> None:
        self.panel.commit(self.oid, self.path, value)


class CheckEditor(Editor):
    def __init__(self, spec, path, panel):
        super().__init__(spec, path, panel)
        self.widget = QCheckBox()
        # clicked, not toggled: from "several" (partly checked) a click checks
        # the box without toggling it.
        self.widget.clicked.connect(lambda on: self.commit(on))

    def show(self, value: bool) -> None:
        self.widget.blockSignals(True)
        if value is SEVERAL:
            self.widget.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            self.widget.setChecked(bool(value))
        self.widget.blockSignals(False)


class PartEditor(CheckEditor):
    """Whether an optional part (a right y axis, a color bar) is there."""

    def show(self, value: Any) -> None:
        super().show(value is not None)


class ChoiceEditor(Editor):
    """A fixed set of values: literals, or the columns of the data sources."""

    def __init__(
        self, spec, path, panel, choices: list[tuple[str, Any]], missing=" (missing)"
    ):
        super().__init__(spec, path, panel)
        self.missing = missing
        """Added to a value not among the choices, as it is shown."""
        self.choices = list(choices)
        if spec.optional:
            self.choices.insert(0, (NONE_TEXT.get(path[-1], "(none)"), None))
        self.widget = QComboBox()
        for text, _ in self.choices:
            self.widget.addItem(text)
        self.widget.activated.connect(lambda i: self.commit(self.choices[i][1]))

    def show(self, value: Any) -> None:
        values = [v for _, v in self.choices]
        if value not in values:
            text = "several" if value is SEVERAL else f"{value}{self.missing}"
            self.choices.append((text, value))
            self.widget.addItem(self.choices[-1][0])
            values.append(value)
        self.widget.blockSignals(True)
        self.widget.setCurrentIndex(values.index(value))
        self.widget.blockSignals(False)


class TextEditor(Editor):
    """A line of text, parsed into the field's type when editing finishes."""

    def __init__(self, spec, path, panel, parse, format_):
        super().__init__(spec, path, panel)
        self.parse = parse
        self.format = format_
        self.line = QLineEdit()
        self.line.editingFinished.connect(self._finish)
        self.widget = self.line

    def show(self, value: Any) -> None:
        self.value = value
        self.line.setText(self._text(value))

    def _text(self, value: Any) -> str:
        return "" if value is None or value is SEVERAL else self.format(value)

    def _finish(self) -> None:
        text = self.line.text().strip()
        if text == self._text(self.value):
            return
        if not text and self.spec.optional:
            self.commit(None)
            return
        try:
            value = self.parse(text)
        except ValueError as exc:
            self.panel.report(f"{'.'.join(self.path)}: {exc}")
            self.show(self.value)
            return
        self.commit(value)


RECENT_COLORS = 5
"""How many recently set colors the color fields offer."""

SWATCHES_PER_ROW = 6

LINESTYLES = [
    ("Solid", "-"),
    ("Dashed", "--"),
    ("Dotted", ":"),
    ("Dash-dot", "-."),
    ("None", "none"),
]
LOCATIONS = [
    "best",
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "right",
    "center left",
    "center right",
    "lower center",
    "upper center",
    "center",
]
UNIT_FORMATS = [("U (V)", "parentheses"), ("U / V", "slash"), ("U [V]", "brackets")]
CHOICES = {
    "linestyle": LINESTYLES,
    "location": [(loc, loc) for loc in LOCATIONS],
    "grid_axis": [("both axes", "both"), ("x only", "x"), ("y only", "y")],
    "grid_which": [
        ("major ticks", "major"),
        ("minor ticks", "minor"),
        ("both", "both"),
    ],
}
CHOICES["grid_linestyle"] = [s for s in LINESTYLES if s[1] != "none"]
CHOICES["data_type"] = [("fractional frequency", "frequency"), ("phase (s)", "phase")]
CHOICES["taus"] = [
    ("octaves: 1, 2, 4, 8 …", "octave"),
    ("decades: 1, 2, 5, 10 …", "decade"),
    ("every m", "all"),
]
CHOICES["unit_format"] = UNIT_FORMATS
CHOICES["encoding"] = ENCODINGS
CHOICES["placement"] = [
    ("outside the corner", "outside"),
    ("inside the corner", "inside"),
]
CHOICES["tick_direction"] = [
    ("outward", "out"),
    ("inward", "in"),
    ("both ways", "inout"),
]
NONE_TEXT = {
    "stylesheet": "Matplotlib's default",
    "tick_direction": "style default",
    "time": "the sample interval below",
    "grid_linestyle": "style default",
    "prefix": "as in the data",
    "marker": "No marker",
    "left_out_marker": "No marker",
    "xerr": "no x errors",
    "yerr": "no y errors",
    "x": "cell numbers",
    "y": "cell numbers",
}
"""What an unset optional choice means, where "(none)" would mislead."""
SUPERSCRIPTS = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
CHOICES["prefix"] = [
    (f"{prefix} (×10{str(power).translate(SUPERSCRIPTS)})", prefix)
    for prefix, power in PREFIXES.items()
]
"""Text and literal fields with a known set of good values."""
COLORMAPS = [
    "viridis",
    "plasma",
    "inferno",
    "magma",
    "cividis",
    "gray",
    "Greys",
    "Blues",
    "Reds",
    "coolwarm",
    "RdBu_r",
    "seismic",
    "twilight",
    "turbo",
]
"""Perceptually uniform maps first, then grey, single-hue and diverging ones;
any other Matplotlib name stays usable, it is just not offered."""


class ColorEditor(TextEditor):
    """The colors of the figure's color cycle, the ones used lately, the color
    another plot is drawn in, any Matplotlib color as text ("C0", "tab:blue",
    "#ff0000"), or one picked from a dialog."""

    def __init__(self, spec, path, panel):
        super().__init__(spec, path, panel, str, str)
        self.widget = QWidget()
        column = QVBoxLayout(self.widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        cycle = [(f"C{i}", c) for i, c in enumerate(_cycle(panel)[:10])]
        self.swatches = self._swatches([*cycle, ("black", "black")])
        self.button = QToolButton()
        self.button.setObjectName("choice")
        self.button.setIcon(theme.icon("plus", theme.MUTED))
        self.button.setToolTip("Pick any color")
        self.button.clicked.connect(self._pick)
        self.recent = self._swatches([(c, c) for c in panel.recent_colors])
        buttons = [*self.swatches.values(), self.button]
        # Six to a row keeps the form as narrow as the panel.
        for start in range(0, len(buttons), SWATCHES_PER_ROW):
            column.addLayout(_row_of(buttons[start : start + SWATCHES_PER_ROW]))
        if self.recent:
            column.addLayout(_row_of(list(self.recent.values())))
        column.addWidget(self.line)
        self.same_as = QToolButton()
        self.same_as.setText("Same as…")
        self.same_as.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.same_as.setMenu(self._same_as_menu())
        self.same_as.setEnabled(bool(self.same_as.menu().actions()))
        column.addLayout(_row_of([self.same_as]))

    def show(self, value: Any) -> None:
        super().show(value)
        for key, swatch in [*self.swatches.items(), *self.recent.items()]:
            swatch.setChecked(key == value)

    def commit(self, value: Any) -> None:
        # Only a color Matplotlib draws: a refused one would break the swatches.
        if (
            value is not None
            and not _CYCLE_COLOR.fullmatch(value)
            and style_problem("color", value) is None
        ):
            self.panel.remember_color(value)
        super().commit(value)

    def _swatches(self, colors: list[tuple[str, str]]) -> dict[str, QToolButton]:
        buttons: dict[str, QToolButton] = {}
        for value, shown in colors:
            swatch = QToolButton()
            swatch.setObjectName("swatch")
            swatch.setCheckable(True)
            swatch.setToolTip(_color_name(shown))
            swatch.setIcon(theme.icon("swatch", to_hex(shown), 18))
            swatch.setIconSize(QSize(18, 18))
            swatch.clicked.connect(lambda _=False, v=value: self.commit(v))
            buttons[value] = swatch
        return buttons

    def _same_as_menu(self) -> QMenu:
        menu = QMenu(self.widget)
        figure = self.panel.document.figure
        for axes in figure.axes if figure is not None else []:
            for artist in axes.artists:
                if artist.id != self.oid and "color" in type(artist).model_fields:
                    menu.addAction(
                        artist_name(artist), lambda a=artist: self._take_color(a)
                    )
        return menu

    def _take_color(self, artist) -> None:
        color = self.panel.drawn_color(artist.id) or artist.color
        if color is not None:
            self.commit(color)

    def _pick(self) -> None:
        color = self.panel.pick_color(self.value)
        if color is not None:
            self.commit(color)


_CYCLE_COLOR = re.compile(r"C\d")
"""A color of the cycle, "C0" to "C9", which follows the style sheet."""

_TABLEAU_NAMES = {to_hex(v): k for k, v in TABLEAU_COLORS.items()}


def _cycle(panel: PropertyPanel) -> list[str]:
    """The colors of the shown figure's color cycle, under its style sheet."""
    figure = panel.document.figure
    with style_context(figure) if figure is not None else nullcontext():
        return list(matplotlib.rcParams["axes.prop_cycle"].by_key().get("color", []))


def _row_of(widgets: list[QWidget]) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(4)
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch(1)
    return row


def _color_name(color: str) -> str:
    return _TABLEAU_NAMES.get(to_hex(color), color)


class FieldsEditor(Editor):
    """Several numbers, each in a field of its own with a small label;
    `combine` turns what is typed (None for an empty field) into the value."""

    def __init__(self, spec, path, panel, labels, placeholder, combine):
        super().__init__(spec, path, panel)
        self.combine = combine
        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.lines: list[QLineEdit] = []
        for text in labels:
            if text:
                row.addWidget(label(text, "caption"))
            line = QLineEdit()
            line.setPlaceholderText(placeholder)
            line.editingFinished.connect(self._finish)
            row.addWidget(line, 1)
            self.lines.append(line)

    def show(self, value: Any) -> None:
        self.value = value
        values = list(value) if value is not None else []
        for i, line in enumerate(self.lines):
            text = f"{values[i]:g}" if i < len(values) else ""
            # What the greyed-out placeholder already says is left empty.
            line.setText("" if text == line.placeholderText() else text)

    def _finish(self) -> None:
        texts = [line.text().strip() for line in self.lines]
        try:
            value = self.combine([number(t) if t else None for t in texts])
        except ValueError as exc:
            self.panel.report(f"{field_name(self.path[-1])}: {exc}")
            return  # left as typed, to be completed
        if value != self.value:
            self.commit(value)


def _extent(values: list[float | None]) -> tuple[float, ...] | None:
    if all(v is None for v in values):
        return None
    if any(v is None for v in values):
        raise ValueError("fill in all four, or none for an automatic extent")
    return tuple(values)


def _ratios(values: list[float | None]) -> list[float] | None:
    if all(v is None for v in values):
        return None
    ratios = [1.0 if v is None else v for v in values]
    if any(r <= 0 for r in ratios):
        raise ValueError("ratios must be more than 0")
    return ratios


class StyleEditor(ChoiceEditor):
    """Matplotlib's style sheets by name, or an .mplstyle file from disk,
    chosen through the last entry."""

    CHOOSE = "Choose file…"

    def __init__(self, spec, path, panel):
        styles = [(s, s) for s in sorted(matplotlib.style.available) if s[0] != "_"]
        super().__init__(spec, path, panel, styles, missing="")
        # Long names such as seaborn-v0_8-colorblind would widen the whole form.
        policy = QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        self.widget.setSizeAdjustPolicy(policy)
        self.widget.setMinimumContentsLength(12)
        self.widget.addItem(self.CHOOSE)
        self.widget.activated.disconnect()
        self.widget.activated.connect(self._chosen)

    def show(self, value: Any) -> None:
        self.value = value
        if value not in [v for _, v in self.choices]:
            # A file goes above "Choose file…", shown by its name.
            self.choices.append((pathlib.Path(value).name, value))
            self.widget.insertItem(len(self.choices) - 1, self.choices[-1][0])
            self.widget.setItemData(
                len(self.choices) - 1, value, Qt.ItemDataRole.ToolTipRole
            )
        self.widget.blockSignals(True)
        self.widget.setCurrentIndex([v for _, v in self.choices].index(value))
        self.widget.blockSignals(False)

    def _chosen(self, index: int) -> None:
        if index < len(self.choices):
            self.commit(self.choices[index][1])
            return
        chosen = self.panel.choose_file("Style sheet", "Style sheets (*.mplstyle)")
        if chosen is None:
            self.show(self.value)
        else:
            self.commit(str(chosen))


def make_editor(spec: Spec, path: Path, panel: PropertyPanel) -> Editor:
    name = path[-1]
    if spec.kind == "bool":
        return CheckEditor(spec, path, panel)
    if spec.kind == "part":
        return PartEditor(spec, path, panel)
    if name in ("marker", "left_out_marker"):
        return _marker_list(spec, path, panel)
    if name == "text":
        return NoteText(spec, path, panel)
    if name == "cmap":
        choices = [(c, c) for c in COLORMAPS]
        return ChoiceEditor(spec, path, panel, choices, missing="")
    if name == "stylesheet":
        return StyleEditor(spec, path, panel)
    if name == "extent":
        sides = ["left", "right", "bottom", "top"]
        return FieldsEditor(spec, path, panel, sides, PLACEHOLDERS[name], _extent)
    if name in ("width_ratios", "height_ratios"):
        layout = _get(find(panel.document.project, panel.document.selected), path[:-1])
        count = layout.cols if name == "width_ratios" else layout.rows
        blank = PLACEHOLDERS[name]
        return FieldsEditor(spec, path, panel, [""] * count, blank, _ratios)
    if name in CHOICES and spec.kind in ("choice", "text"):
        return ChoiceEditor(spec, path, panel, CHOICES[name])
    if spec.kind == "choice":
        return ChoiceEditor(spec, path, panel, [(str(o), o) for o in spec.options])
    if spec.kind == "column":
        return ChoiceEditor(spec, path, panel, panel.document.column_choices())
    if spec.kind == "array":
        return ChoiceEditor(spec, path, panel, panel.document.array_choices())
    if spec.kind == "color":
        editor = ColorEditor(spec, path, panel)
    else:
        parse, format_ = _TEXT[spec.kind]
        if name in SHOWN:
            parse, format_ = _on_screen(parse, format_, *SHOWN[name])
        editor = TextEditor(spec, path, panel, parse, format_)
    if spec.optional:
        nested = len(path) > 1  # e.g. an axis label, which no legend shows
        placeholder = PLACEHOLDERS.get(".".join(path), PLACEHOLDERS.get(name))
        if nested and name == "label":
            placeholder = "none"
        editor.line.setPlaceholderText(placeholder or "none")
    return editor


def _area(size: float) -> float:
    if size <= 0:
        raise ValueError(f"{size:g} is not a marker size; it must be more than 0")
    return size * size


def _counted_from_one(value: int) -> int:
    if value < 1:
        raise ValueError(
            f"{value} is too small: rows, columns and lines are counted from 1"
        )
    return value - 1


SHOWN: dict[str, tuple[Callable[[Any], Any], Callable[[Any], Any]]] = {
    "row": (lambda value: value + 1, _counted_from_one),
    "col": (lambda value: value + 1, _counted_from_one),
    "header_row": (lambda value: value + 1, _counted_from_one),
    "size": (lambda area: round(math.sqrt(area), 6), _area),
}
"""Fields shown in other numbers than the model keeps them, with the
conversions to the screen and back: rows, columns and lines are counted
from 1 on screen and from 0 in the model; points keep their marker area in
pt², as Matplotlib's scatter takes it, and show its size in pt like lines."""


def _on_screen(parse, format_, to_screen, from_screen):
    def parse_shown(text: str) -> Any:
        return from_screen(parse(text))

    def format_shown(value: Any) -> str:
        return format_(to_screen(value))

    return parse_shown, format_shown


SEPARATED = "separated by commas, or by semicolons with decimal commas"


def _pair(text: str) -> tuple[float, float]:
    values = numbers(text)
    if len(values) != 2:
        raise ValueError(f"needs two numbers {SEPARATED}, got {len(values)}")
    return values[0], values[1]


def _bins(text: str) -> int | list[float]:
    """A number of bins ("20") or their edges ("0, 1, 2.5" or "0; 1; 2,5")."""
    if "," not in text and ";" not in text:
        return whole(text)
    return numbers(text)


def _quad(text: str) -> tuple[float, float, float, float]:
    values = numbers(text)
    if len(values) != 4:
        raise ValueError(f"needs four numbers {SEPARATED}, got {len(values)}")
    return values[0], values[1], values[2], values[3]


def _join(values) -> str:
    return ", ".join(repr(v) if isinstance(v, float) else str(v) for v in values)


_TEXT: dict[str, tuple[Callable[[str], Any], Callable[[Any], str]]] = {
    "text": (str, str),
    "int": (whole, str),
    "float": (number, repr),
    "pair": (_pair, _join),
    "quad": (_quad, _join),
    "bins": (_bins, lambda v: str(v) if isinstance(v, int) else _join(v)),
    "floats": (numbers, _join),
    "strings": (lambda t: [part.strip() for part in t.split(",")], _join),
}


# --- helpers -----------------------------------------------------------------


def _get(obj: BaseModel, path: Path) -> Any:
    for part in path:
        obj = getattr(obj, part)
    return obj


def _is_union(annotation: Any) -> bool:
    return typing.get_origin(annotation) in (typing.Union, types.UnionType)


def _shape(obj: BaseModel) -> tuple:
    """What decides the form's layout: the object, and its optional parts."""
    parts = tuple(
        getattr(obj, name, None) is None
        for name in ("y_right", "colorbar", "panel_labels", "band", "inset", "result")
    )
    layout = getattr(obj, "layout", None)
    grid = (layout.rows, layout.cols) if layout is not None else None
    return (obj.id, type(obj), parts, grid)


def _axes_of(project, artist_id: str) -> Axes | None:
    for figure in project.figures:
        for axes in figure.axes:
            if any(a.id == artist_id for a in axes.artists):
                return axes
    return None


def _form_label(name: str) -> QLabel:
    return _caption(field_name(name))


def _caption(text: str) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName("caption")
    widget.setFixedWidth(LABEL_WIDTH)
    widget.setWordWrap(True)
    return widget


def _section_name(name: str) -> str:
    return SECTION_NAMES.get(name, field_name(name))


def _read_only_text(name: str, value: Any, document: Document) -> str:
    if name == "sha256":
        return f"{value[:12]}…"
    if name == "row_count" and value is None:
        return "not recorded"  # imported before figscribe counted rows
    if name == "parent":
        for figure in document.project.figures:
            for axes in figure.axes:
                if axes.id == value:
                    return panel_name(figure, axes)
        return f"{value} (missing)"
    if name == "target":
        try:
            return artist_name(find(document.project, value))
        except CommandError:
            return f"{value} (missing)"
    return str(value)


def _describe(obj: BaseModel, document: Document) -> tuple[str, str]:
    """Kicker and title of the panel's header."""
    if isinstance(obj, Figure):
        return "Figure", f"{obj.name} · {size_text(obj)}"
    if isinstance(obj, Axes):
        for figure in document.project.figures:
            if obj in figure.axes:
                return "Panel", panel_name(figure, obj)
        return "Panel", "Panel"
    if hasattr(obj, "format"):
        return "Data file", PurePath(obj.path).name
    kind = getattr(obj, "kind", "")
    return KIND_NAMES.get(kind, type(obj).__name__), artist_name(obj)


def _marker_list(spec: Spec, path: Path, panel: PropertyPanel) -> ChoiceEditor:
    """Every Matplotlib marker, drawn, in a list. A plot's own marker may be
    "none" (error bars alone); a left-out point's may also be the plot's."""
    choices = [(name, value) for value, name in ALL_MARKERS]
    if path[-1] == "left_out_marker":
        choices.insert(0, ("Like the plot", LIKE_THE_PLOT))
    elif not spec.optional:
        choices.append(("No marker", "none"))
    choices.append(("Custom…", CUSTOM))
    editor = MarkerList(spec, path, panel, choices, missing="")
    for index, (_, value) in enumerate(editor.choices):
        editor.widget.setItemIcon(index, marker_icon(value))
    return editor


CUSTOM = object()
"""The list entry that asks for a marker of one's own."""


class MarkerList(ChoiceEditor):
    """A list of markers whose last entry asks for any other."""

    def show(self, value: Any) -> None:
        self.value = value
        super().show(value)

    def commit(self, value: Any) -> None:
        if value is not CUSTOM:
            super().commit(value)
            return
        typed = self.panel.ask_marker(None if self.value is SEVERAL else self.value)
        if typed is None:
            self.show(self.value)
        else:
            super().commit(typed)


CHOICES["left_out_linestyle"] = [("Like the plot", LIKE_THE_PLOT), *LINESTYLES]


def _result_lines(fit: FitCurve, found) -> list[tuple[str, str]]:
    """(name, value) of a fit's result as the card shows and copies it."""
    result = fit.result
    if result is None:
        return []
    lines = []
    for name, value in result.parameters.items():
        held = f"{value:.6g} (held)" if name in fit.fixed else None
        lines.append((name, held or with_error(value, result.uncertainties.get(name))))
    if result.reduced_chi_square is not None:
        lines.append(("χ²ᵣ", f"{result.reduced_chi_square:.2f}"))
    if found is not None:
        lines += [
            ("Points fitted", f"{found.used} of {found.total}"),
            ("Residual RMS", f"{found.rms:.3g}"),
            ("Largest residual", f"{found.largest:.3g} (row {found.row + 1})"),
        ]
    return lines


class NoteText(Editor):
    """A note's text over several lines, taken on leaving the field or with
    Ctrl+Enter (Cmd+Enter on macOS)."""

    def __init__(self, spec, path, panel):
        super().__init__(spec, path, panel)
        self.widget = TextBox()
        self.widget.setTabChangesFocus(True)
        self.widget.setFixedHeight(84)  # four lines, then it scrolls
        self.widget.finished.connect(self._finish)
        self.value = ""

    def show(self, value: Any) -> None:
        self.value = value or ""
        self.widget.setPlainText(self.value)

    def _finish(self) -> None:
        text = self.widget.toPlainText().strip()
        if text == self.value:
            return
        if not text:
            self.panel.report("A note needs some text; delete the note instead.")
            self.show(self.value)
            return
        self.commit(text)
