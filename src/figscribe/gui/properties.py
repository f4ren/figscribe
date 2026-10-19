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

from figscribe.commands import CommandError, SetField, find
from figscribe.fit import FitError, refit
from figscribe.gui import theme
from figscribe.gui.document import Document
from figscribe.gui.names import (
    KIND_NAMES,
    artist_name,
    field_name,
    panel_name,
    size_text,
    with_error,
)
from figscribe.gui.widgets import Section, label
from figscribe.io.errors import DataError
from figscribe.model import ArrayRef, Axes, ColumnRef, Figure, FitCurve

SKIPPED = {
    "id",
    "kind",
    "format",
    "sources",
    "figures",
    "axes",
    "artists",
    "columns",
    "y_right",
    "model",
    "initial_values",
    "result",
    "bins",
}
"""Fields with no editor here: identity, item lists (edited in the outline),
and values that need a dedicated editor (fits, histogram bins)."""

READ_ONLY = {"path", "sha256", "target"}
"""Shown, but changed only through their own actions (re-import, refit)."""

COLOR_FIELDS = {"color", "edgecolor"}

Path = tuple[str, ...]


@dataclass
class Spec:
    """How a field is edited, derived from its annotation."""

    kind: str
    optional: bool = False
    options: tuple = ()
    model: type[BaseModel] | None = None


def spec_for(name: str, annotation: Any) -> Spec | None:
    """The editor for a field, or None when the panel has none for it."""
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
    if origin is tuple and args == (float, float):
        return Spec("pair", optional)
    if origin is list and args == (float,):
        return Spec("floats", optional)
    if origin is list and args == (str,):
        return Spec("strings", optional)
    if annotation is ColumnRef:
        return Spec("column", optional)
    if annotation is ArrayRef:
        return None  # 2-D data needs its own picker
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return None if optional else Spec("model", model=annotation)
    return None


SECTIONS = {
    "x": "Data",
    "y": "Data",
    "xerr": "Data",
    "yerr": "Data",
    "values": "Data",
    "c": "Data",
    "target": "Data",
    "name": "Size",
    "width_mm": "Size",
    "height_mm": "Size",
    "dpi": "Size",
    "unit_format": "Style",
    "stylesheet": "Style",
    "title": "Panel",
    "grid": "Panel",
    "path": "File",
    "sha256": "File",
    "label": "Legend",
    "visible": "More",
    "zorder": "More",
    "axis": "More",
    "row": "More",
    "col": "More",
    "rowspan": "More",
    "colspan": "More",
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
SECTION_NAMES = {"x": "X axis", "y": "Y axis", "y_right": "Right y axis"}
"""Titles of nested models' sections, where they differ from the field's name."""
LABEL_WIDTH = 116

ORDER = ["Data", "Size", "Panel", "File", "Reading", "Look", "Style", "Legend"]
COLLAPSED = {"More", "Layout"}
"""Sections that start folded: rarely needed, but always there."""

PLACEHOLDERS = {
    "label": "not in the legend",
    "color": "automatic",
    "edgecolor": "automatic",
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
    "wspace": "automatic",
}

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
        self._shown: tuple[str, type] | None = None
        self._fit_result = None
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
        body = QWidget()
        body.setObjectName("sidePanel")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        obj = self._selected_object()
        if obj is None:
            self._shown = None
            hint = label(
                "Select a figure, panel, plot or data file to edit it.", "hint"
            )
            hint.setContentsMargins(16, 16, 16, 16)
            layout.addWidget(hint)
        else:
            self._shown = (obj.id, type(obj))
            layout.addWidget(self._header(obj))
        self._error = label("", "error")
        self._error.setContentsMargins(16, 8, 16, 0)
        self._error.hide()
        layout.addWidget(self._error)
        if obj is not None:
            self._fill(obj, layout)
        layout.addStretch(1)
        self.setWidget(body)

    def refresh(self) -> None:
        """Show the model's current values; rebuild if the object changed."""
        obj = self._selected_object()
        if obj is None or self._shown != (obj.id, type(obj)):
            self.rebuild()
            return
        if isinstance(obj, FitCurve) and obj.result != self._fit_result:
            self.rebuild()
            return
        self._update_header(obj)
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
            self.document.push(SetField(oid, path, value))
        except CommandError as exc:
            self.report(str(exc))
            self.refresh()
        else:
            self._error.hide()

    def report(self, message: str) -> None:
        self._error.setText(message)
        self._error.show()

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
        kicker, title = _describe(obj, self.document)
        self._kicker.setText(kicker.upper())
        self._title.setText(title)

    def _fill(self, obj: BaseModel, layout: QVBoxLayout) -> None:
        fallback = "Reading" if hasattr(obj, "format") else "Look"
        groups: dict[str, list[str]] = {}
        nested: list[str] = []
        for name, field in type(obj).model_fields.items():
            if name in SKIPPED:
                continue
            spec = spec_for(name, field.annotation)
            if spec is not None and spec.kind == "model":
                nested.append(name)
                continue
            groups.setdefault(SECTIONS.get(name, fallback), []).append(name)
        if "Look" in groups:
            groups["Look"].sort(key=lambda n: LOOK.index(n) if n in LOOK else 99)
        titles = {_section_name(n): n for n in nested}
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
            self._row(form, model, (*prefix, name), top=False)

    def _row(
        self, form: QFormLayout, obj: BaseModel, path: Path, top: bool = True
    ) -> None:
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
        form.addRow(_form_label(name), editor.widget)

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
                grid.addWidget(label(with_error(value, error), "value"), row, 1)
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
        again = QPushButton("Fit again with the current data")
        again.setObjectName("link")
        again.clicked.connect(lambda: self.fit_again(fit.id))
        self.fit_again_button = again
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
        try:
            return find(self.document.project, oid)
        except CommandError:
            return None

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


class ChoiceEditor(Editor):
    """A fixed set of values: literals, or the columns of the data sources."""

    def __init__(self, spec, path, panel, choices: list[tuple[str, Any]]):
        super().__init__(spec, path, panel)
        self.choices = list(choices)
        if spec.optional:
            self.choices.insert(0, ("(none)", None))
        self.widget = QComboBox()
        for text, _ in self.choices:
            self.widget.addItem(text)
        self.widget.activated.connect(lambda i: self.commit(self.choices[i][1]))

    def show(self, value: Any) -> None:
        values = [v for _, v in self.choices]
        if value not in values:
            self.choices.append((f"{value} (missing)", value))
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
CHOICES = {"linestyle": LINESTYLES, "location": [(loc, loc) for loc in LOCATIONS]}
CHOICES["unit_format"] = UNIT_FORMATS
"""Text and literal fields with a known set of good values."""


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
            options.append((None, "No marker"))
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
    if name in CHOICES and spec.kind in ("choice", "text"):
        return ChoiceEditor(spec, path, panel, CHOICES[name])
    if spec.kind == "choice":
        return ChoiceEditor(spec, path, panel, [(str(o), o) for o in spec.options])
    if spec.kind == "column":
        return ChoiceEditor(spec, path, panel, panel.document.column_choices())
    if spec.kind == "color":
        editor = ColorEditor(spec, path, panel)
    elif name == "marker" and spec.kind == "text":
        editor = MarkerEditor(spec, path, panel)
    else:
        parse, format_ = _TEXT[spec.kind]
        editor = TextEditor(spec, path, panel, parse, format_)
    if spec.optional:
        editor.line.setPlaceholderText(PLACEHOLDERS.get(name, "none"))
    return editor


def _float(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{text!r} is not a number") from None


def _int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{text!r} is not a whole number") from None


def _floats(text: str) -> list[float]:
    return [_float(part.strip()) for part in text.split(",")]


def _pair(text: str) -> tuple[float, float]:
    values = _floats(text)
    if len(values) != 2:
        raise ValueError(f"needs two numbers separated by a comma, got {len(values)}")
    return values[0], values[1]


def _join(values) -> str:
    return ", ".join(repr(v) if isinstance(v, float) else str(v) for v in values)


_TEXT: dict[str, tuple[Callable[[str], Any], Callable[[Any], str]]] = {
    "text": (str, str),
    "int": (_int, str),
    "float": (_float, repr),
    "pair": (_pair, _join),
    "floats": (_floats, _join),
    "strings": (lambda t: [part.strip() for part in t.split(",")], _join),
}


# --- helpers -----------------------------------------------------------------


def _get(obj: BaseModel, path: Path) -> Any:
    for part in path:
        obj = getattr(obj, part)
    return obj


def _is_union(annotation: Any) -> bool:
    return typing.get_origin(annotation) in (typing.Union, types.UnionType)


def _form_label(name: str) -> QLabel:
    widget = QLabel(field_name(name))
    widget.setObjectName("caption")
    widget.setFixedWidth(LABEL_WIDTH)
    widget.setWordWrap(True)
    return widget


def _section_name(name: str) -> str:
    return SECTION_NAMES.get(name, field_name(name))


def _read_only_text(name: str, value: Any, document: Document) -> str:
    if name == "sha256":
        return f"{value[:12]}…"
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
