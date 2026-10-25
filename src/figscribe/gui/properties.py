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

import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Literal

from pydantic import BaseModel
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.commands import CommandError, Macro, SetField, find
from figscribe.fit import FitError, refit
from figscribe.gui import theme
from figscribe.gui.axisform import AXIS_TITLES, AxisForm, axis_summary
from figscribe.gui.document import AXIS_FIELDS, Document, axis_id, split_axis
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
from figscribe.gui.widgets import Section, label
from figscribe.io.errors import DataError
from figscribe.io.refresh import read_differently, reading_options
from figscribe.model import (
    ArrayRef,
    Axes,
    AxisSpec,
    Colorbar,
    ColumnRef,
    ExpressionFit,
    Figure,
    FitCurve,
    FitResult,
    PredefinedFit,
    Project,
)
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

COLOR_FIELDS = {"color", "edgecolor", "grid_color"}

Path = tuple[str, ...]


@dataclass
class Spec:
    """How a field is edited, derived from its annotation."""

    kind: str
    optional: bool = False
    options: tuple = ()
    model: type[BaseModel] | None = None


OPTIONAL_PARTS: dict[str, type[BaseModel]] = {"y_right": AxisSpec, "colorbar": Colorbar}
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
    "bins": "Data",
    "c": "Data",
    "target": "Data",
    "name": "Size",
    "width_mm": "Size",
    "height_mm": "Size",
    "dpi": "Size",
    "unit_format": "Style",
    "stylesheet": "Style",
    "title": "Panel",
    "title_size": "Panel",
    "grid": "Panel",
    "grid_axis": "Panel",
    "grid_which": "Panel",
    "grid_color": "Panel",
    "font_size": "Style",
    "tick_direction": "Style",
    "ticks_all_sides": "Style",
    "path": "File",
    "sha256": "File",
    "label": "Legend",
    "visible": "More",
    "zorder": "More",
    "axis": "Data",
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
]
"""How the "Look" section starts; other fields follow in model order."""
SECTION_NAMES = {
    "x": "X axis",
    "y": "Y axis",
    "y_right": "Right y axis",
    "colorbar": "Color bar",
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
]
COLLAPSED = {"More", "Layout"}
"""Sections that start folded: rarely needed, but always there."""

PLACEHOLDERS = {
    "label": "not in the legend",
    "color": "automatic",
    "edgecolor": "automatic",
    "grid_color": "automatic",
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
    "extent": "automatic",
    "position": "by location",
    "delimiter": "spaces or tabs",
    "header_row": "no names",
    "comment": "none",
    "array": "the first",
    "width_ratios": "equal",
    "height_ratios": "equal",
}

TIPS = {
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
    "title": "Text above the panel; LaTeX between $ signs.",
    "title_size": "Font size of the title; empty follows the figure.",
    "y_right": "A second y axis on the right, for plots in another unit.",
    "grid": "Grid lines behind the plots.",
    "grid_axis": "Which axes get grid lines.",
    "grid_which": "Grid lines at the numbered ticks, the minor ticks, or both.",
    "grid_color": "Color of the grid lines, e.g. dimgray or #696969; empty "
    "keeps the style's light gray.",
    "row": "Grid row of the panel, from the top, starting at 0.",
    "col": "Grid column of the panel, from the left, starting at 0.",
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
    "edgecolor": "Color of the marker outlines; empty follows the style.",
    "linestyle": "How the line is drawn: solid, dashed, dash-dotted, dotted, or none "
    "for points only.",
    "linewidth": "Line width in pt.",
    "marker": "The symbol drawn at each data point.",
    "markersize": "Size of the markers in pt.",
    "size": "Area of the markers in pt².",
    "capsize": "Length of the caps at the ends of the error bars in pt; 0 for none.",
    "elinewidth": "Line width of the error bars in pt.",
    "values": "The column whose values are counted.",
    "bins": "A number of bins of equal width, or their edges, e.g. 0, 1, 2.5.",
    "density": "Scale the bars to a total area of 1, to compare data sets of different"
    " size.",
    "histtype": "Filled bars, only their outline, or a filled outline.",
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
    "header_row": "The line with the column names, counted from 0; empty for a file "
    "without names.",
    "skip_rows": "Lines between the names and the numbers, such as a line of units.",
    "comment": "Lines starting with this are ignored; empty for none.",
    "dataset": "Where the data lies inside the HDF5 file, e.g. /run3/voltage.",
    "array": "Which array of the .npz archive to plot.",
}
"""Explanations shown when the mouse rests on a field, by field name, or by
"Class.field" where the same name means something else there."""


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
            if isinstance(section.header, QToolButton):
                self._folded[title] = not section.expanded
        self.editors = {}
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
        if obj is None:
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
        if axis is not None and obj is not None:
            oid = self.document.selected
            self.axis_form = AxisForm(
                self, axis[0], axis[1], layout, lambda: self.axis_range(oid)
            )
            self.axis_form.show(obj)
        elif obj is not None:
            self._fill(obj, layout)
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
        if isinstance(obj, FitCurve) and obj.result != self._fit_result:
            self.rebuild()
            return
        self._update_header(obj)
        if self.axis_form is not None:
            self.axis_form.show(obj)
        for path, editor in self.editors.items():
            editor.show(_get(obj, path))

    def commit(self, oid: str, path: Path, value: Any) -> None:
        """Set the field at `path` of object `oid` to `value`.

        Ignored unless `oid` is still the selected object: an editor torn down
        by a selection change can still report its last input.
        """
        if oid != self.document.selected:
            return
        try:
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
        return ("axis", oid) if split_axis(oid) else _shape(obj)

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
        result = fit.result
        if result is None:
            grid.addWidget(label("Not fitted yet.", "hint"), 0, 0)
        else:
            for row, (name, value) in enumerate(result.parameters.items()):
                error = result.uncertainties.get(name)
                grid.addWidget(label(GREEK.get(name, name), "value"), row, 0)
                shown = f"{value:.6g} (held)" if name in fit.fixed else None
                grid.addWidget(
                    label(shown or with_error(value, error), "value"), row, 1
                )
            row = len(result.parameters)
            if result.reduced_chi_square is not None:
                grid.addWidget(label("χ²ᵣ", "value"), row, 0)
                chi = label(f"{result.reduced_chi_square:.2f}", "value")
                grid.addWidget(chi, row, 1)
            if not result.converged:
                warning = label("The fit did not converge.", "error")
                grid.addWidget(warning, row + 1, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        outer.addWidget(card)
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

    def fit_again(self, fit_id: str) -> None:
        """Run the fit again, e.g. after its data or start values changed."""
        try:
            self.document.push(refit(self.document.project, fit_id, self.document.data))
        except (FitError, CommandError, DataError) as exc:
            self.report(str(exc))

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
        self.widget.toggled.connect(lambda on: self.commit(on))

    def show(self, value: bool) -> None:
        self.widget.blockSignals(True)
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
            self.choices.append((f"{value}{self.missing}", value))
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
        return "" if value is None else self.format(value)

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


SWATCHES = [("C0", "Blue"), ("C1", "Orange"), ("C2", "Green"), ("C3", "Red")]
SWATCHES.append(("black", "Black"))

MARKERS = [("o", "Circle"), ("s", "Square"), ("^", "Triangle"), ("D", "Diamond")]

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
CHOICES["unit_format"] = UNIT_FORMATS
CHOICES["encoding"] = ENCODINGS
CHOICES["tick_direction"] = [
    ("outward", "out"),
    ("inward", "in"),
    ("both ways", "inout"),
]
NONE_TEXT = {
    "tick_direction": "style default",
    "prefix": "as in the data",
    "marker": "No marker",
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
    """A few swatches of the color cycle, any Matplotlib color as text
    ("C0", "tab:blue", "#ff0000"), or one picked from a dialog."""

    def __init__(self, spec, path, panel):
        super().__init__(spec, path, panel, str, str)
        self.widget = QWidget()
        column = QVBoxLayout(self.widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.swatches: dict[str, QToolButton] = {}
        for value, name in SWATCHES:
            swatch = QToolButton()
            swatch.setObjectName("swatch")
            swatch.setCheckable(True)
            swatch.setToolTip(name)
            swatch.setIcon(theme.icon("swatch", theme.plot_color(value, 0), 18))
            swatch.setIconSize(QSize(18, 18))
            swatch.clicked.connect(lambda _=False, v=value: self.commit(v))
            row.addWidget(swatch)
            self.swatches[value] = swatch
        self.button = QToolButton()
        self.button.setObjectName("choice")
        self.button.setIcon(theme.icon("plus", theme.MUTED))
        self.button.setToolTip("Pick any color")
        self.button.clicked.connect(self._pick)
        row.addWidget(self.button)
        row.addStretch(1)
        column.addLayout(row)
        column.addWidget(self.line)

    def show(self, value: Any) -> None:
        super().show(value)
        for key, swatch in self.swatches.items():
            swatch.setChecked(key == value)

    def _pick(self) -> None:
        color = self.panel.pick_color(self.value)
        if color is not None:
            self.commit(color)


class MarkerEditor(TextEditor):
    """The common markers as buttons; any Matplotlib marker as text."""

    def __init__(self, spec, path, panel):
        super().__init__(spec, path, panel, str, str)
        self.line.setPlaceholderText("any Matplotlib marker")
        self.widget = QWidget()
        column = QVBoxLayout(self.widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(4)
        options = list(MARKERS)
        if spec.optional:
            options.append((None, NONE_TEXT["marker"]))
        self.buttons: dict[str | None, QToolButton] = {}
        for value, name in options:
            button = QToolButton()
            button.setObjectName("choice")
            button.setCheckable(True)
            button.setToolTip(name)
            glyph = "marker-none" if value is None else f"marker-{value}"
            button.setIcon(theme.icon(glyph, theme.INK))
            button.clicked.connect(lambda _=False, v=value: self.commit(v))
            row.addWidget(button)
            self.buttons[value] = button
        row.addStretch(1)
        column.addLayout(row)
        column.addWidget(self.line)

    def show(self, value: Any) -> None:
        super().show(value)
        for key, button in self.buttons.items():
            button.setChecked(key == value)


def make_editor(spec: Spec, path: Path, panel: PropertyPanel) -> Editor:
    name = path[-1]
    if spec.kind == "bool":
        return CheckEditor(spec, path, panel)
    if spec.kind == "part":
        return PartEditor(spec, path, panel)
    if name == "cmap":
        choices = [(c, c) for c in COLORMAPS]
        return ChoiceEditor(spec, path, panel, choices, missing="")
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
    elif name == "marker" and spec.kind == "text":
        editor = MarkerEditor(spec, path, panel)
    else:
        parse, format_ = _TEXT[spec.kind]
        editor = TextEditor(spec, path, panel, parse, format_)
    if spec.optional:
        nested = len(path) > 1  # e.g. an axis label, which no legend shows
        placeholder = "none" if nested and name == "label" else PLACEHOLDERS.get(name)
        editor.line.setPlaceholderText(placeholder or "none")
    return editor


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
        for name in ("y_right", "colorbar", "inset", "result")
    )
    return (obj.id, type(obj), parts)


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
