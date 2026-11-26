"""The editor for one axis: range, ticks and label, in the words of a plot.

Selected by clicking the axis in the preview or its line in a panel's form.
Unlike the generated forms, it groups what belongs together ("major ticks
every 50") and speaks in the axis's shown unit: with values shown in kHz,
ranges and steps are entered in kHz and stored in Hz.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from itertools import pairwise
from typing import TYPE_CHECKING, Any, NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.commands import CommandError, Macro, SetField, set_breaks
from figscribe.gui.breaks import current_breaks, panel_index, proposed_break
from figscribe.gui.numbers import number, numbers
from figscribe.gui.widgets import label
from figscribe.model import AxisSpec
from figscribe.model.breaks import breaks_blocked
from figscribe.render.labels import unit_shown
from figscribe.render.ticks import (
    PREFIXES,
    as_drawn,
    counted_interval,
    reversed_axis,
    too_many_ticks,
)

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
NUMBER_FORMATS = [
    ("automatic", "auto"),
    ("fixed decimals", "fixed"),
    ("scientific", "scientific"),
]
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
    "breaks": "Cuts a stretch out of the axis, with a narrow gap and break marks: "
    "for a measurement far from the rest. Nothing is shown within a break, and "
    "no line is drawn across it. Linear x and left y axes only; panels that "
    "share the axis are broken alike.",
    "reverse": "Draws the axis backwards, the highest value first, as wavenumbers "
    "and binding energies are shown; also while the range is automatic. A range "
    "typed with the higher end first does the same.",
    "linthresh": "Around zero, a symmetric log axis is linear within ± this value.",
    "number_format": "How the numbers are written: as Matplotlib chooses, with "
    "a fixed number of decimals, or each as a power of ten (2.5×10³). For a "
    "decimal comma, see the figure's settings.",
    "decimals": "Places after the decimal mark; for scientific numbers, those "
    "in front of the ×.",
    "major": "Where the numbered ticks go.",
    "labels": "Text for each tick value, separated by commas; empty for numbers.",
    "minor": "Unnumbered ticks between the numbered ones.",
    "labelpad": "How far the label stands from the numbers, in pt; empty follows "
    "the style. Needs a label. Where the figure lines labels up, a panel's own "
    "distance moves its label alone.",
    "label_size": "Font size of the axis label in pt; empty follows the figure.",
    "tick_size": "Font size of the numbers in pt; empty follows the figure.",
}


def major_mode(spec: AxisSpec) -> str:
    """How the major ticks are set: "values", "step" or "auto"."""
    if spec.ticks is not None:
        return "values"
    return "step" if spec.major_step is not None else "auto"


def axis_settings(spec: AxisSpec, field: str = "x") -> list[tuple[str, str]]:
    """(section, caption) of each row the axis form shows for `spec`, in
    order, for finding them without the form open."""
    mode = major_mode(spec)
    rows = [
        ("Label", "Label"),
        ("Label", "Unit"),
        ("Label", "Show values in"),
        ("Label", "Label size (pt)"),
        ("Label", "Label distance (pt)"),
        ("Scale", "Type"),
        ("Scale", "From"),
        ("Scale", "Direction"),
    ]
    if field != "y_right":  # the right y axis cannot be broken
        rows.append(("Scale", "Breaks"))
    if spec.scale == "symlog":
        rows.append(("Scale", "Linear within ±"))
    rows.append(("Scale", "Number format"))
    if spec.number_format != "auto":
        rows.append(("Scale", "Decimals"))
    rows += [("Scale", "Number size (pt)"), ("Ticks", "Major ticks")]
    if mode != "auto":
        rows.append(("Ticks", "Distance" if mode == "step" else "Values"))
    if mode == "values":
        rows.append(("Ticks", "Tick labels"))
    rows.append(("Ticks", "Minor ticks"))
    return rows


class BreakRow(NamedTuple):
    widget: QWidget
    start: QLineEdit
    end: QLineEdit
    remove: QToolButton


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
        self.waiting: set[QWidget] = set()
        """The fields hidden until another setting makes them useful."""

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
        self.label_size = self._line(form, "Label size (pt)", "label_size", "default")
        self.label_size.editingFinished.connect(
            lambda: self._number("label_size", self.label_size)
        )
        self.labelpad = self._line(form, "Label distance (pt)", "labelpad", "default")
        self.labelpad.editingFinished.connect(
            lambda: self._number("labelpad", self.labelpad)
        )

        form = panel._section("Scale", layout)
        self.scale = self._combo(form, "Type", "scale", SCALES)
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
        self.reverse = QCheckBox("Highest value first")
        self._add(form, "Direction", self.reverse, "reverse")
        self.reverse.clicked.connect(self._set_reversed)
        self.break_rows: list[BreakRow] = []
        self._typing = False
        """Whether an empty row waits for a break to be typed."""
        holder = QWidget()
        stack = QVBoxLayout(holder)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(6)
        self._break_stack = QVBoxLayout()
        self._break_stack.setSpacing(6)
        stack.addLayout(self._break_stack)
        # One line: a wrapped label would squeeze the fields above it.
        self.break_hint = label("Type the ends of the cut.", "caption")
        stack.addWidget(self.break_hint)
        self.add_break = QPushButton("Add a break")
        self.add_break.clicked.connect(self._add_break)
        stack.addWidget(self.add_break, 0, Qt.AlignmentFlag.AlignLeft)
        self._add(form, "Breaks", holder, "breaks")
        self.breaks_holder = holder
        self.linthresh = self._line(form, "Linear within ±", "linthresh")
        self.linthresh.editingFinished.connect(
            lambda: self._number("symlog_linthresh", self.linthresh, shown=True)
        )
        self.number_format = self._combo(
            form, "Number format", "number_format", NUMBER_FORMATS
        )
        self.number_format.activated.connect(
            lambda i: self._set(number_format=self.number_format.itemData(i))
        )
        self.decimals = QSpinBox()
        self.decimals.setRange(0, 10)
        self.decimals.setKeyboardTracking(False)  # one change, not one per digit
        self._add(form, "Decimals", self.decimals, "decimals")
        self.decimals.valueChanged.connect(lambda n: self._set(decimals=n))
        self.tick_size = self._line(form, "Number size (pt)", "tick_size", "default")
        self.tick_size.editingFinished.connect(
            lambda: self._number("tick_size", self.tick_size)
        )

        form = panel._section("Ticks", layout)
        self.major = self._combo(form, "Major ticks", "major", MAJOR_MODES)
        self.major.activated.connect(self._set_major_mode)
        self.major_value = self._line(form, "Distance", "major")
        self.major_caption = form.labelForField(self.major_value)
        self.major_value.editingFinished.connect(self._set_major_value)
        self.tick_labels = self._line(form, "Tick labels", "labels", "numbers")
        self.tick_labels.editingFinished.connect(self._set_tick_labels)
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
        self._add(form, "Minor ticks", row, "minor")
        self.minor.activated.connect(self._set_minor)
        self.count.valueChanged.connect(lambda _: self._set_minor())
        self.minor_hint = label("", "caption")
        self.minor_hint.setWordWrap(True)
        form.addRow(self.minor_hint)

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
            self.reverse,
            self.linthresh,
            self.major,
            self.major_value,
            self.tick_labels,
            self.minor,
            self.count,
            self.labelpad,
            self.label_size,
            self.tick_size,
            self.number_format,
            self.decimals,
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
        self.reverse.setChecked(reversed_axis(spec))
        self._show_breaks()
        self._visible(self.linthresh, spec.scale == "symlog")
        _text(self.linthresh, self._shown(spec.symlog_linthresh))
        self._show_number_format(spec)

        mode = major_mode(spec)
        self.major.setCurrentIndex(self.major.findData(mode))
        self._visible(self.major_value, mode != "auto")
        self._visible(self.tick_labels, mode == "values")
        unit = unit_shown(spec) or ""
        self.major_caption.setText("Distance" if mode == "step" else "Values")
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

        _text(self.labelpad, _number_text(spec.labelpad))
        _text(self.label_size, _number_text(spec.label_size))
        _text(self.tick_size, _number_text(spec.tick_size))

    def _show_number_format(self, spec: AxisSpec) -> None:
        self.number_format.setCurrentIndex(
            self.number_format.findData(spec.number_format)
        )
        self.decimals.setValue(spec.decimals)
        self._visible(self.decimals, spec.number_format != "auto")
        typed = spec.tick_labels is not None  # they are shown as typed
        for name, widget in (
            ("number_format", self.number_format),
            ("decimals", self.decimals),
        ):
            reason = "No effect while tick labels are typed. " if typed else ""
            caption = self._forms[widget].labelForField(widget)
            for part in (caption, widget):
                part.setEnabled(not typed)
                part.setToolTip(reason + TIPS[name])

    def _show_breaks(self) -> None:
        document = self.panel.document
        index = panel_index(document, self.axes_id)
        self._visible(self.breaks_holder, self.field != "y_right")
        if index is None or self.field == "y_right":
            return
        breaks = current_breaks(document, self.axes_id, self.field)
        if len(breaks) + self._typing != len(self.break_rows):
            for row in self.break_rows:
                # Hiding a focused field finishes its editing: not any more.
                row.start.blockSignals(True)
                row.end.blockSignals(True)
                row.widget.hide()
                row.widget.deleteLater()
            count = len(breaks) + self._typing
            self.break_rows = [self._break_row(i) for i in range(count)]
        for row, (start, end) in zip(self.break_rows, breaks, strict=False):
            _text(row.start, self._shown(start))
            _text(row.end, self._shown(end))
        self.break_hint.setVisible(self._typing)
        why = breaks_blocked(document.figure, index, self.field)
        tip = TIPS["breaks"] if why is None else f"{why[0].upper()}{why[1:]}."
        self.add_break.setEnabled(why is None)
        self.add_break.setToolTip(tip)
        for row in self.break_rows:
            row.start.setEnabled(why is None)
            row.end.setEnabled(why is None)

    def _break_row(self, number: int) -> BreakRow:
        widget = QWidget()
        line = QHBoxLayout(widget)
        line.setContentsMargins(0, 0, 0, 0)
        start, end = QLineEdit(), QLineEdit()
        remove = QToolButton()
        remove.setText("×")
        remove.setToolTip("Remove this break")
        start.setToolTip("Where the stretch cut out begins")
        end.setToolTip("Where the stretch cut out ends")
        line.addWidget(start, 1)
        line.addWidget(QLabel("to"))
        line.addWidget(end, 1)
        line.addWidget(remove)
        self._break_stack.addWidget(widget)
        row = BreakRow(widget, start, end, remove)
        start.editingFinished.connect(lambda: self._set_break(number))
        end.editingFinished.connect(lambda: self._set_break(number))
        remove.clicked.connect(lambda: self._remove_break(number))
        return row

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
        changed = self.spec.model_copy(update=values)
        interval = changed.limits or self.current()
        index = panel_index(self.panel.document, self.axes_id)
        if interval and index is not None:  # a break's stretch has no ticks
            # The figure as it would be: a wider range can bring a break into view.
            figure = self.panel.document.figure
            panels = list(figure.axes)
            panels[index] = panels[index].model_copy(update={self.field: changed})
            figure = figure.model_copy(update={"axes": panels})
            counted = as_drawn(figure, index, self.field, changed)
            interval = counted_interval(counted, interval)
        problem = too_many_ticks(changed, interval) if interval else None
        if problem is not None:  # left as typed, to be corrected
            message = problem[1]
            self.panel.report(f"{message[0].upper()}{message[1:]}.")
            return
        title = AXIS_TITLES[self.field]
        try:
            self.panel.document.push(Macro(f"Change the {title}", steps))
        except CommandError as exc:
            self.panel.report(str(exc))
            self.show(self.spec)
        else:
            self.panel.clear_report()

    def _set_breaks(self, breaks: list[tuple[float, float]]) -> None:
        """Give the axis, and those sharing it, these breaks, as one step."""
        document = self.panel.document
        breaks = sorted(breaks)
        if any(not a < b for a, b in breaks):
            self.panel.report("A break needs a start below its end.")
            return
        if any(not end < start for (_, end), (start, _) in pairwise(breaks)):
            self.panel.report("Breaks must be apart from each other.")
            return
        if breaks == current_breaks(document, self.axes_id, self.field):
            return
        try:
            document.push(
                set_breaks(document.project, self.axes_id, self.field, breaks)
            )
        except CommandError as exc:
            self.panel.report(str(exc))
            self.show(self.spec)
        else:
            self.panel.clear_report()

    def _set_break(self, number: int) -> None:
        breaks = current_breaks(self.panel.document, self.axes_id, self.field)
        row = self.break_rows[number]
        if number >= len(breaks):
            self._set_typed(row, breaks)
            return
        ends = []
        for edit, old in zip((row.start, row.end), breaks[number], strict=True):
            text = edit.text().strip()
            if text == self._shown(old):  # unchanged: not rounded to what shows
                ends.append(old)
                continue
            try:
                ends.append(self._parsed(text))
            except ValueError as exc:
                self.panel.report(str(exc))
                return
        self._set_breaks([*breaks[:number], tuple(ends), *breaks[number + 1 :]])

    def _set_typed(self, row: BreakRow, breaks: list) -> None:
        """Take the break typed into the empty row, once both ends are there."""
        texts = [edit.text().strip() for edit in (row.start, row.end)]
        if not all(texts):
            return
        try:
            new = tuple(self._parsed(text) for text in texts)
        except ValueError as exc:
            self.panel.report(str(exc))
            return
        self._typing = False
        self._set_breaks([*breaks, new])
        if current_breaks(self.panel.document, self.axes_id, self.field) == breaks:
            self._typing = True  # refused: left as typed, to be corrected

    def _remove_break(self, number: int) -> None:
        breaks = current_breaks(self.panel.document, self.axes_id, self.field)
        if number >= len(breaks):
            self._typing = False
            self._show_breaks()
            return
        self._set_breaks([b for i, b in enumerate(breaks) if i != number])

    def _add_break(self) -> None:
        """Cut out an empty stretch of the data; where it has none worth it, an
        empty row to type the break into."""
        found = proposed_break(self.panel.document, self.axes_id, self.field)
        if found is not None:
            breaks = current_breaks(self.panel.document, self.axes_id, self.field)
            self._typing = False
            self._set_breaks([*breaks, found])
            return
        self._typing = True
        self._show_breaks()
        self.break_rows[-1].start.setFocus()

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

    def _set_reversed(self, checked: bool) -> None:
        """The box shows an axis as reversed also when only its range is typed
        highest end first; turning it off then puts the range right as well."""
        if checked:
            self._set(inverted=True)
            return
        limits = self.spec.limits
        if limits is not None and limits[0] > limits[1]:
            self._set(inverted=False, limits=(limits[1], limits[0]))
        else:
            self._set(inverted=False)

    def _set_major_mode(self) -> None:
        mode = self.major.currentData()
        if mode == "auto":
            self._set(ticks=None, tick_labels=None, major_step=None)
        else:
            self.major_caption.setText("Distance" if mode == "step" else "Values")
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
                values = [value * self._factor() for value in numbers(text)]
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
                value = number(text)
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
        return number(text) * self._factor()

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
        (self.waiting.discard if visible else self.waiting.add)(widget)


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
    summary = f"{name} · {scale} · {shown}"
    if spec.breaks:
        factor = 10.0 ** PREFIXES[spec.prefix] if spec.prefix else 1.0
        cut = ", ".join(f"{a / factor:g} – {b / factor:g}" for a, b in spec.breaks)
        summary += f" · broken at {cut}"
    return summary
