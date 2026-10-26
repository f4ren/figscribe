"""Every field of the property panel and the axis form, operated as a person
does: click the box, pick another entry, type and press Enter.

For each object of a project that has every kind (`everything.py`), each of
its fields must change the model, leave a figure that can be drawn, change
what is drawn, and come back with undo. Since the panel is generated from the
model, a new field is in this test without anyone adding it; a field whose
right outcome here is something else goes into EXPECTED with the reason, a
known problem into KNOWN with the roadmap item that fixes it. pytest-qt fails
the test on any exception that reaches Qt's event loop.

A crash takes the whole test run down rather than failing one test; that is
what it should do.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QToolButton,
    QWidget,
)

from figscribe.commands import find
from figscribe.gui import Document
from figscribe.gui.document import axis_id, split_axis
from figscribe.gui.properties import PropertyPanel
from figscribe.model import Project, dumps
from figscribe.render.figure import render

from .everything import build

TEXTS = [
    "2",
    "1",
    "0.5",
    "Probe",
    "1; 2",
    "0.1; 0.1; 0.3; 0.3",
    "5; 10",
    "s",
    "tab:red",
]
"""What is typed into a text field, in turn, until the model takes one."""

TYPED = {
    "dpi": ["100"],
    "stylesheet": ["classic"],
    "rows": ["3"],
    "cols": ["3"],
    "zorder": ["5", "0.5"],  # to the front, or to the back
    "array": ["background"],
    "decimal": [","],
    "comment": ["%"],
    "major_value": ["1"],
}
"""What is typed instead into fields where those texts would not do, tried
in turn like the entries of a list until what is drawn changes."""

CHOICES = 6
"""How many other entries of a list are tried, as a person would before giving
up; a list of every column of every file is long."""

UNSEEN = "nothing drawn changes"
REFUSED = "no input changed the model"
EXPECTED = {
    "Figure.name": (UNSEEN, "names the exported files, not drawn"),
    "LinePlot.left_out_note": (UNSEEN, "a comment in the script, not drawn"),
    "ScatterPlot.left_out_note": (UNSEEN, "a comment in the script, not drawn"),
    "ErrorbarPlot.left_out_note": (UNSEEN, "a comment in the script, not drawn"),
    "Figure.dpi": (UNSEEN, "only the PNG export's resolution; the preview has its own"),
    "Annotation.label": (UNSEEN, "a note has no legend entry"),
    "ImagePlot.label": (UNSEEN, "an image has no legend entry"),
    "ColorMesh.label": (UNSEEN, "a color mesh has no legend entry"),
    "CsvSource.encoding": (UNSEEN, "the file is plain ASCII, read alike in each"),
    "CsvSource.comment": (UNSEEN, "no line of the file has the new mark"),
    "CsvSource.delimiter": (
        REFUSED,
        "the file has commas; no other separator reads it",
    ),
    "CsvSource.decimal": (REFUSED, "a comma, the only other mark, is the separator"),
    "CsvSource.header_row": (
        "the figure cannot be drawn: DataError: no column 't'",
        "another header line renames the columns the plots use, and says so",
    ),
}
"""Fields whose right outcome in this project is not a visible change: the
start of what the test reports, and why."""

KNOWN = {
    "GridLayout.width_ratios": "B8 item 2 follow-up: a count unlike the grid's "
    "is taken, and the figure cannot be drawn",
    "GridLayout.height_ratios": "B8 item 2 follow-up: a count unlike the grid's "
    "is taken, and the figure cannot be drawn",
    "ColorMesh.x": "B8 item 4: used only together with y, which says nothing",
    "ColorMesh.y": "B8 item 4: used only together with x, which says nothing",
}
"""Fields with a problem that is planned to be fixed: the roadmap item."""


def _artist(kind: str, index: int = 0) -> Callable[[Project], str]:
    def pick(project: Project) -> str:
        found = [
            a for ax in project.figures[0].axes for a in ax.artists if a.kind == kind
        ]
        return found[index].id

    return pick


OBJECTS: dict[str, Callable[[Project], str]] = {
    "figure": lambda p: p.figures[0].id,
    "panel": lambda p: p.figures[0].axes[0].id,
    "inset": lambda p: p.figures[0].axes[4].id,
    "x axis": lambda p: axis_id(p.figures[0].axes[0].id, "x"),
    "y axis": lambda p: axis_id(p.figures[0].axes[0].id, "y"),
    "right y axis": lambda p: axis_id(p.figures[0].axes[0].id, "y_right"),
    "line": _artist("line"),
    "points": _artist("scatter"),
    "error bars": _artist("errorbar"),
    "fit": _artist("fit"),
    "residuals": _artist("residual"),
    "note": _artist("annotation"),
    "histogram": _artist("histogram"),
    "image": _artist("image"),
    "color mesh": _artist("colormesh"),
    "CSV file": lambda p: p.sources[0].id,
    "NumPy file": lambda p: p.sources[1].id,
}


@pytest.fixture(scope="module")
def project_file(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("everything"))


@pytest.mark.slow
@pytest.mark.parametrize("name", OBJECTS)
def test_every_field_works(qtbot, project_file: Path, name: str) -> None:
    document = Document.open(project_file)
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    panel.resize(400, 900)
    panel.show()
    oid = OBJECTS[name](document.project)
    document.select(oid)
    for section in panel.sections.values():  # open what is folded, as a person
        if isinstance(section.header, QToolButton) and not section.expanded:
            section.header.click()
    start = (dumps(document.project), _image(document))
    problems = []
    for field in _fields(panel):
        key = f"{type(_owner(document, oid, field)).__name__}.{_name(field)}"
        outcome = _try(document, panel, oid, field, start)
        if key in EXPECTED:
            expected, why = EXPECTED[key]
            if outcome is None or not outcome.startswith(expected):
                got = outcome or "a visible change"
                problems.append(f"{field}: expected {expected!r} ({why}), got {got}")
        elif key in KNOWN:
            if outcome is None:
                problems.append(f"{field}: works now; take {key} out of KNOWN")
        elif outcome is not None:
            problems.append(f"{field}: {outcome}")
    assert not problems, f"{name}:\n  " + "\n  ".join(problems)


def _fields(panel: PropertyPanel) -> list[str]:
    """The names of the fields shown for the selected object."""
    if panel.axis_form is not None:
        return sorted(
            name
            for name, widget in vars(panel.axis_form).items()
            if isinstance(widget, QLineEdit | QComboBox | QSpinBox | QCheckBox)
        )
    return [".".join(path) for path in panel.editors]


def _widget(panel: PropertyPanel, field: str) -> QWidget:
    """The field's input, found anew: the form may have been built again."""
    if panel.axis_form is not None:
        return getattr(panel.axis_form, field)
    widget = panel.editors[tuple(field.split("."))].widget
    if isinstance(widget, QCheckBox | QComboBox | QLineEdit | QSpinBox):
        return widget
    lines = widget.findChildren(QLineEdit)
    if len(lines) > 1:
        return widget  # a field per number, filled together
    return lines[0] if lines else widget.findChild(QComboBox)


def _try(document, panel, oid, field, start):
    """Operate one field; what went wrong, or None."""
    before, image = start
    widget = _widget(panel, field)
    if not widget.isVisibleTo(panel) or not widget.isEnabled():
        return None  # shown only with another setting, and tried there
    outcome = REFUSED
    for attempt in _inputs(panel, field, widget):
        attempt()
        if dumps(document.project) == before:
            document.select(oid)
            continue
        try:
            changed = _image(document) != image
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            changed = f"the figure cannot be drawn: {type(exc).__name__}: {exc}"
        document.undo()
        document.select(oid)
        if dumps(document.project) != before:
            return "undo does not restore the project"
        if changed is True:
            outcome = None
            break
        outcome = changed or UNSEEN
        if not isinstance(widget, QComboBox) and _name(field) not in TYPED:
            break  # a typed value is taken as it is; other entries are tried
    if outcome == REFUSED:
        return f"{outcome} ({panel.error or 'no message'})"
    return outcome


def _inputs(panel: PropertyPanel, field: str, widget: QWidget):
    """Ways a person would change the field, to be tried in turn."""
    form = panel.axis_form
    if form is not None and field in ("low", "high"):  # a range has two ends

        def both_ends() -> None:
            form.low.setText("0.5")
            form.high.setText("3")
            getattr(form, field).editingFinished.emit()

        yield both_ends
    elif isinstance(widget, QCheckBox):
        yield widget.click
    elif isinstance(widget, QSpinBox):
        yield lambda: widget.setValue(widget.value() + 1)
    elif isinstance(widget, QComboBox):
        current = widget.currentIndex()
        others = [i for i in range(widget.count()) if i != current]
        for i in others[:CHOICES]:
            yield lambda i=i: _choose(panel, field, i)
    elif not isinstance(widget, QLineEdit):
        yield lambda: _fill(panel, field)
    else:
        for text in TYPED.get(_name(field), TEXTS):
            yield lambda text=text: _type(panel, field, text)


def _choose(panel: PropertyPanel, field: str, index: int) -> None:
    widget = _widget(panel, field)
    widget.setCurrentIndex(index)
    widget.activated.emit(index)
    form = panel.axis_form
    if form is not None and field == "major" and form.major_value.isVisibleTo(panel):
        _type(panel, "major_value", TYPED["major_value"][0])  # a way, then where


def _fill(panel: PropertyPanel, field: str) -> None:
    """Type 1, 2, 3 ... into a field that has one box per number."""
    lines = _widget(panel, field).findChildren(QLineEdit)
    for number, line in enumerate(lines, start=1):
        line.setText(str(number))
    lines[-1].editingFinished.emit()


def _name(field: str) -> str:
    return field.split(".")[-1]


def _type(panel: PropertyPanel, field: str, text: str) -> None:
    widget = _widget(panel, field)
    widget.setText(text)
    widget.editingFinished.emit()


def _owner(document: Document, oid: str, field: str):
    """The model object the field belongs to, for its class name."""
    if (axis := split_axis(oid)) is not None:
        return getattr(find(document.project, axis[0]), axis[1])
    owner = find(document.project, oid)
    for part in field.split(".")[:-1]:
        owner = getattr(owner, part)
    return owner


def _image(document: Document) -> str:
    figure = render(document.figure, document.data)
    figure.set_dpi(72)
    FigureCanvasAgg(figure).draw()
    return hashlib.sha1(bytes(figure.canvas.buffer_rgba())).hexdigest()
