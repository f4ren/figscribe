"""The editor for one axis: range, ticks and label, in the words of a plot.

Selected by clicking the axis in the preview or its line in a panel's form.
Unlike the generated forms, it groups what belongs together ("major ticks
every 50") and speaks in the axis's shown unit: with values shown in kHz,
ranges and steps are entered in kHz and stored in Hz.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from figscribe.commands import CommandError, Macro, SetField
from figscribe.gui.widgets import label
from figscribe.model import AxisSpec
from figscribe.render.labels import unit_shown
from figscribe.render.ticks import PREFIXES

if TYPE_CHECKING:
    from figscribe.gui.properties import PropertyPanel

AXIS_TITLES = {"x": "x axis", "y": "y axis", "y_right": "Right y axis"}
SCALES = [("linear", "linear"), ("logarithmic", "log"), ("symmetric log", "symlog")]
MAJOR_MODES = [
    ("automatically", "auto"),
    ("every …", "step"),
    ("at these values", "values"),
]
MINOR_MODES = [("none", "off"), ("automatically", "on"), ("between majors:", "count")]
SUPERSCRIPTS = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")

TIPS = {
    "label": "The quantity, e.g. $f$ or Frequency; LaTeX between $ signs.",
    "unit": "The unit of the data, e.g. Hz. It is joined to the label as the "
    "figure's unit style says.",
    "prefix": "Show the numbers divided by a power of ten, with the unit "
    "prefixed: 225000 Hz as 225 kHz. The data stay as they are.",
    "scale": "How values are spaced along the axis.",
    "range": "Leave empty for an automatic range; the grey numbers show the "
    "current one.",
    "linthresh": "Around zero, a symmetric log axis is linear within ± this value.",
    "major": "Where the numbered ticks go.",
    "labels": "Text for each tick value, separated by commas; empty for numbers.",
    "minor": "Unnumbered ticks between the numbered ones.",
    "label_size": "Font size of the axis label in pt; empty follows the figure.",
    "tick_size": "Font size of the numbers in pt; empty follows the figure.",
}


class AxisForm:
    """The sections for one axis of a panel, inside the property panel."""

    def __init__(
        self,
        panel: PropertyPanel,
        axes_id: str,
        field: str,
        layout: QVBoxLayout,
        current: Callable[[], tuple[float, float] | None],
    ):
        self.panel = panel
        self.axes_id = axes_id
        self.field = field
        self.current = current
        """The range the axis shows right now, in data units."""
        self.spec = AxisSpec()
        self._forms: dict[QWidget, QFormLayout] = {}

        form = panel._section("Label", layout)
        self.label = self._line(form, "Label", "label")
        self.label.editingFinished.connect(
            lambda: self._set(label=self.label.text().strip() or None)
        )
        self.unit = self._line(form, "Unit", "unit", "none")
        self.unit.editingFinished.connect(
            lambda: self._set(unit=self.unit.text().strip() or None)
        )
        self.prefix = self._combo(form, "Show values in", "prefix", [])
        self.prefix.activated.connect(
            lambda i: self._set(prefix=self.prefix.itemData(i))
        )

        form = panel._section("Range", layout)
        self.scale = self._combo(form, "Scale", "scale", SCALES)
        self.scale.activated.connect(lambda i: self._set(scale=self.scale.itemData(i)))
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.low = QLineEdit()
        self.high = QLineEdit()
        line.addWidget(self.low, 1)
        line.addWidget(QLabel("to"))
        line.addWidget(self.high, 1)
        self._add(form, "From", row, "range")
        self.low.editingFinished.connect(self._set_range)
        self.high.editingFinished.connect(self._set_range)
        self.linthresh = self._line(form, "Linear within ±", "linthresh")
        self.linthresh.editingFinished.connect(
            lambda: self._number("symlog_linthresh", self.linthresh, shown=True)
        )

        form = panel._section("Major ticks", layout)
        self.major = self._combo(form, "Placed", "major", MAJOR_MODES)
        self.major.activated.connect(self._set_major_mode)
        self.major_value = self._line(form, "", "major")
        self.major_value.editingFinished.connect(self._set_major_value)
        self.tick_labels = self._line(form, "Labels", "labels", "numbers")
        self.tick_labels.editingFinished.connect(self._set_tick_labels)

        form = panel._section("Minor ticks", layout)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.minor = QComboBox()
        for text, value in MINOR_MODES:
            self.minor.addItem(text, value)
        self.count = QSpinBox()
        self.count.setRange(1, 19)
        line.addWidget(self.minor, 1)
        line.addWidget(self.count)
        self._add(form, "Placed", row, "minor")
        self.minor.activated.connect(self._set_minor)
        self.count.valueChanged.connect(lambda _: self._set_minor())
        self.minor_hint = label("", "caption")
        self.minor_hint.setWordWrap(True)
        form.addRow(self.minor_hint)

        form = panel._section("Text size", layout)
        self.label_size = self._line(form, "Label (pt)", "label_size", "default")
        self.label_size.editingFinished.connect(
            lambda: self._number("label_size", self.label_size)
        )
        self.tick_size = self._line(form, "Numbers (pt)", "tick_size", "default")
        self.tick_size.editingFinished.connect(
            lambda: self._number("tick_size", self.tick_size)
        )

    # --- showing --------------------------------------------------------------

    def show(self, spec: AxisSpec) -> None:
        """Show `spec`; called again after every change of the model."""
        self.spec = spec
        widgets = [
            self.label,
            self.unit,
            self.prefix,
            self.scale,
            self.low,
            self.high,
            self.linthresh,
            self.major,
            self.major_value,
            self.tick_labels,
            self.minor,
            self.count,
            self.label_size,
            self.tick_size,
        ]
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self._show(spec)
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _show(self, spec: AxisSpec) -> None:
        _text(self.label, spec.label)
        _text(self.unit, spec.unit)
        self.prefix.clear()
        self.prefix.addItem(f"{spec.unit or 'numbers'}, as in the data", None)
        for prefix, power in PREFIXES.items():
            shown = unit_shown(spec.model_copy(update={"prefix": prefix}))
            text = shown if spec.unit else f"×10{str(power).translate(SUPERSCRIPTS)}"
            self.prefix.addItem(text, prefix)
        self.prefix.setCurrentIndex(self.prefix.findData(spec.prefix))
        self.scale.setCurrentIndex(self.scale.findData(spec.scale))

        now = self.current()
        if spec.limits is not None:
            low, high = spec.limits
            self.low.setText(self._shown(low))
            self.high.setText(self._shown(high))
        else:
            self.low.clear()
            self.high.clear()
        self.low.setPlaceholderText(self._shown(now[0]) if now else "automatic")
        self.high.setPlaceholderText(self._shown(now[1]) if now else "automatic")
        self._visible(self.linthresh, spec.scale == "symlog")
        _text(self.linthresh, self._shown(spec.symlog_linthresh))

        mode = (
            "values"
            if spec.ticks is not None
            else ("step" if spec.major_step is not None else "auto")
        )
        self.major.setCurrentIndex(self.major.findData(mode))
        self._visible(self.major_value, mode != "auto")
        self._visible(self.tick_labels, mode == "values")
        unit = unit_shown(spec) or ""
        if mode == "step":
            _text(self.major_value, self._shown(spec.major_step))
            self.major_value.setPlaceholderText(
                f"distance{' in ' + unit if unit else ''}"
            )
        elif mode == "values":
            _text(self.major_value, ", ".join(self._shown(v) for v in spec.ticks))
            self.major_value.setPlaceholderText("values, separated by commas")
        _text(self.tick_labels, ", ".join(spec.tick_labels or []) or None)

        if not spec.minor_ticks:
            minor = "off"
        elif spec.minor_divisions is None:
            minor = "on"
        else:
            minor = "count"
            self.count.setValue(spec.minor_divisions - 1)
        self.minor.setCurrentIndex(self.minor.findData(minor))
        self.count.setVisible(minor == "count")
        ignored = minor == "count" and spec.scale == "log" and spec.major_step is None
        self.minor_hint.setText(
            "On a log axis, a count needs major ticks every fixed distance."
            if ignored
            else ""
        )
        self.minor_hint.setVisible(ignored)

        _text(self.label_size, _number_text(spec.label_size))
        _text(self.tick_size, _number_text(spec.tick_size))

    # --- changing -------------------------------------------------------------

    def _set(self, **values: Any) -> None:
        """Change fields of the axis in one undo step."""
        steps = [
            SetField(self.axes_id, (self.field, name), value)
            for name, value in values.items()
            if getattr(self.spec, name) != value
        ]
        if not steps:
            return
        title = AXIS_TITLES[self.field]
        try:
            self.panel.document.push(Macro(f"Change the {title}", steps))
        except CommandError as exc:
            self.panel.report(str(exc))
            self.show(self.spec)
        else:
            self.panel.clear_report()

    def _set_range(self) -> None:
        low, high = self.low.text().strip(), self.high.text().strip()
        if not low and not high:
            self._set(limits=None)
            return
        now = self.current()
        try:
            a = self._parsed(low) if low else (now[0] if now else None)
            b = self._parsed(high) if high else (now[1] if now else None)
        except ValueError as exc:
            self.panel.report(str(exc))
            return
        if a is None or b is None:
            self.panel.report("Enter both ends of the range.")
            return
        self._set(limits=(a, b))

    def _set_major_mode(self) -> None:
        mode = self.major.currentData()
        if mode == "auto":
            self._set(ticks=None, tick_labels=None, major_step=None)
        else:
            self._visible(self.major_value, True)
            self._visible(self.tick_labels, mode == "values")
            self.major_value.clear()
            self.major_value.setFocus()

    def _set_major_value(self) -> None:
        text = self.major_value.text().strip()
        if not text:
            return
        try:
            if self.major.currentData() == "step":
                self._set(ticks=None, tick_labels=None, major_step=self._parsed(text))
            else:
                values = [self._parsed(part) for part in text.split(",")]
                self._set(ticks=values, major_step=None)
        except ValueError as exc:
            self.panel.report(str(exc))

    def _set_tick_labels(self) -> None:
        text = self.tick_labels.text().strip()
        labels = [part.strip() for part in text.split(",")] if text else None
        self._set(tick_labels=labels)

    def _set_minor(self) -> None:
        mode = self.minor.currentData()
        if mode == "off":
            self._set(minor_ticks=False)
        elif mode == "on":
            self._set(minor_ticks=True, minor_divisions=None)
        else:
            self._set(minor_ticks=True, minor_divisions=self.count.value() + 1)

    def _number(self, name: str, edit: QLineEdit, shown: bool = False) -> None:
        text = edit.text().strip()
        try:
            if not text:
                value = None
            elif shown:
                value = self._parsed(text)
            else:
                value = _float(text)
        except ValueError as exc:
            self.panel.report(str(exc))
            return
        self._set(**{name: value})

    # --- the shown unit ---------------------------------------------------------

    def _factor(self) -> float:
        prefix = self.spec.prefix
        return 10.0 ** PREFIXES[prefix] if prefix is not None else 1.0

    def _shown(self, value: float | None) -> str:
        """A value in data units as the axis shows it."""
        if value is None:
            return ""
        return f"{value / self._factor():.6g}"

    def _parsed(self, text: str) -> float:
        """A number typed in the shown unit, in data units."""
        return _float(text) * self._factor()

    # --- widgets ------------------------------------------------------------------

    def _line(
        self, form: QFormLayout, text: str, tip: str, placeholder: str = ""
    ) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        self._add(form, text, edit, tip)
        return edit

    def _combo(self, form: QFormLayout, text: str, tip: str, items) -> QComboBox:
        combo = QComboBox()
        for item_text, value in items:
            combo.addItem(item_text, value)
        self._add(form, text, combo, tip)
        return combo

    def _add(self, form: QFormLayout, text: str, widget: QWidget, tip: str) -> None:
        caption = label(text, "caption")
        caption.setFixedWidth(116)
        caption.setToolTip(TIPS[tip])
        widget.setToolTip(TIPS[tip])
        form.addRow(caption, widget)
        self._forms[widget] = form

    def _visible(self, widget: QWidget, visible: bool) -> None:
        self._forms[widget].setRowVisible(widget, visible)


def plain(text: str) -> str:
    """LaTeX as plain text for a summary: "$\\Delta t$" as "Δ t"."""
    text = re.sub(r"\\([A-Za-z]+)", lambda m: GREEK.get(m.group(1), m.group(1)), text)
    text = re.sub(
        r"\^\{?(-?\d+)\}?", lambda m: m.group(1).translate(SUPERSCRIPTS), text
    )
    return text.replace("$", "").replace("{", "").replace("}", "")


GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "Delta": "Δ",
    "epsilon": "ε",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "omega": "ω",
    "Omega": "Ω",
    "times": "×",
}


def _text(edit: QLineEdit, value: str | None) -> None:
    if not edit.hasFocus():
        edit.setText(value or "")


def _number_text(value: float | None) -> str | None:
    return None if value is None else f"{value:g}"


def _float(text: str) -> float:
    try:
        return float(text.replace(",", ".") if text.count(",") == 1 else text)
    except ValueError:
        raise ValueError(f"{text!r} is not a number") from None


def axis_summary(spec: AxisSpec) -> str:
    """One line about an axis for a panel's form: "f (kHz) · linear · auto"."""
    unit = unit_shown(spec)
    name = plain(spec.label) if spec.label else "no label"
    unit = plain(unit) if unit else unit
    if unit:
        name = f"{name} ({unit})"
    if spec.limits is not None:
        factor = 10.0 ** PREFIXES[spec.prefix] if spec.prefix else 1.0
        low, high = (v / factor for v in spec.limits)
        shown = f"{low:g} – {high:g}"
    else:
        shown = "automatic range"
    scale = dict((v, t) for t, v in SCALES)[spec.scale]
    return f"{name} · {scale} · {shown}"
