"""The property panel: an editor for every field of the selected object.

The form is generated from the pydantic fields at run time, so a field added
to the model shows up here without GUI code. Each editor turns its input into
a SetField command; the model validates it, and a refused value is reported
and the editor shows the model's value again. Field constraints such as
`alpha` in [0, 1] are enforced by the model, not repeated here.
"""

from __future__ import annotations

import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.commands import CommandError, SetField, find
from figscribe.gui.document import Document
from figscribe.model import ArrayRef, ColumnRef, Project

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


class PropertyPanel(QScrollArea):
    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pick_color: Callable[[str | None], str | None] = self._pick_color
        """Asks for a color; replaced in tests."""
        self.editors: dict[Path, Editor] = {}
        self._shown: tuple[str, type] | None = None
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
        self.editors = {}
        body = QWidget()
        layout = QVBoxLayout(body)
        self._error = QLabel()
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color: #b00020")
        self._error.hide()
        layout.addWidget(self._error)

        obj = self._selected_object()
        if obj is None:
            self._shown = None
            hint = QLabel("Select a figure, axes, plot or data source to edit it.")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        else:
            self._shown = (obj.id, type(obj))
            title = QLabel(f"<b>{_title(obj)}</b>")
            layout.addWidget(title)
            layout.addWidget(self._form(obj, ()))
        layout.addStretch(1)
        self.setWidget(body)

    def refresh(self) -> None:
        """Show the model's current values; rebuild if the object changed."""
        obj = self._selected_object()
        if obj is None or self._shown != (obj.id, type(obj)):
            self.rebuild()
            return
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

    def _form(self, model: BaseModel, prefix: Path) -> QWidget:
        box = QWidget() if not prefix else QGroupBox(_label(prefix[-1]))
        form = QFormLayout(box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for name, field in type(model).model_fields.items():
            if name in SKIPPED:
                continue
            path = (*prefix, name)
            value = getattr(model, name)
            if name in READ_ONLY:
                label = QLabel(str(value))
                label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                label.setWordWrap(True)
                form.addRow(_label(name), label)
                continue
            spec = spec_for(name, field.annotation)
            if spec is None:
                continue
            if spec.kind == "model":
                form.addRow(self._form(value, path))
                continue
            editor = make_editor(spec, path, self)
            editor.show(value)
            self.editors[path] = editor
            form.addRow(_label(name), editor.widget)
        return box

    def _selected_object(self) -> BaseModel | None:
        oid = self.document.selected
        if oid is None:
            return None
        try:
            return find(self.document.project, oid)
        except CommandError:
            return None

    def _pick_color(self, current: str | None) -> str | None:
        color = QColorDialog.getColor(QColor(current or "#1f77b4"), self, "Color")
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
        if spec.optional:
            self.line.setPlaceholderText("(none)")
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


class ColorEditor(TextEditor):
    """A Matplotlib color as text ("C0", "tab:blue", "#ff0000"), or picked."""

    def __init__(self, spec, path, panel):
        super().__init__(spec, path, panel, str, str)
        self.button = QToolButton()
        self.button.setText("…")
        self.button.setToolTip("Pick a color")
        self.button.clicked.connect(self._pick)
        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.line)
        row.addWidget(self.button)

    def _pick(self) -> None:
        color = self.panel.pick_color(self.value)
        if color is not None:
            self.commit(color)


def make_editor(spec: Spec, path: Path, panel: PropertyPanel) -> Editor:
    if spec.kind == "bool":
        return CheckEditor(spec, path, panel)
    if spec.kind == "choice":
        return ChoiceEditor(spec, path, panel, [(str(o), o) for o in spec.options])
    if spec.kind == "column":
        return ChoiceEditor(spec, path, panel, _columns(panel.document.project))
    if spec.kind == "color":
        return ColorEditor(spec, path, panel)
    parse, format_ = _TEXT[spec.kind]
    return TextEditor(spec, path, panel, parse, format_)


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


def _columns(project: Project) -> list[tuple[str, ColumnRef]]:
    choices = []
    for source in project.sources:
        for column in source.columns:
            ref = ColumnRef(source=source.id, column=column)
            choices.append((f"{source.path}: {column}", ref))
    return choices


def _get(obj: BaseModel, path: Path) -> Any:
    for part in path:
        obj = getattr(obj, part)
    return obj


def _is_union(annotation: Any) -> bool:
    return typing.get_origin(annotation) in (typing.Union, types.UnionType)


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _title(obj: BaseModel) -> str:
    kind = getattr(obj, "kind", None) or getattr(obj, "format", None)
    name = type(obj).__name__
    return f"{name} ({kind})" if kind and kind not in name.lower() else name
