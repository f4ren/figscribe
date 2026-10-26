"""One axis at a time: selecting it, and its range, ticks and label."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.commands import SetField
from figscribe.gui import Document, MainWindow
from figscribe.gui.document import axis_id, split_axis
from figscribe.gui.preview import Preview
from figscribe.gui.properties import PropertyPanel


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = MainWindow(Document.open(example))
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    qtbot.waitExposed(win)
    win.show_error = lambda title, exc: None
    win.ask = lambda title, question: True  # closing discards the changes
    return win


@pytest.fixture
def document(window) -> Document:
    return window.document


@pytest.fixture
def panel(window) -> PropertyPanel:
    return window.properties


def _axes(document: Document):
    return document.figure.axes[0]


def _enter(edit, text: str) -> None:
    edit.setText(text)
    edit.editingFinished.emit()


def _choose(combo, data) -> None:
    combo.setCurrentIndex(combo.findData(data))
    combo.activated.emit(combo.currentIndex())


def test_an_axis_is_selected_on_its_own(document) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "x"))
    assert document.selected == f"{axes.id}/x"
    assert split_axis(document.selected) == (axes.id, "x")
    document.select(axis_id(axes.id, "y_right"))  # there is none
    assert document.selected is None


def test_the_panel_form_opens_an_axis(panel, document) -> None:
    axes = _axes(document)
    document.select(axes.id)
    panel.axis_links["y"].click()
    assert document.selected == axis_id(axes.id, "y")
    assert panel._kicker.text().startswith("Y AXIS · ")
    assert panel._title.text() == "U (V) · linear · automatic range"
    assert list(panel.sections) == [
        "Label",
        "Range",
        "Major ticks",
        "Minor ticks",
        "Text size",
    ]


def test_the_range_shows_what_is_drawn_and_is_entered_in_the_shown_unit(
    panel, document
) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "x"))
    form = panel.axis_form
    low, high = (float(e.placeholderText()) for e in (form.low, form.high))
    assert low < 0.5 and 9.5 < high < 11  # the automatic range of t in s
    _choose(form.prefix, "m")
    assert _axes(document).x.prefix == "m"
    assert form.unit.text() == "s" and form.prefix.currentText() == "ms"
    assert float(form.high.placeholderText()) > 9000  # now in ms
    _enter(form.low, "2000")
    _enter(form.high, "8000")
    assert _axes(document).x.limits == (2.0, 8.0)  # stored in s
    assert document.history.undo_text == "Change the x axis"
    assert form.low.text() == "2000"
    _enter(form.low, "")
    _enter(form.high, "")
    assert _axes(document).x.limits is None


def test_one_empty_end_keeps_the_current_one(panel, document) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "y"))
    form = panel.axis_form
    _enter(form.high, "2")
    low, high = _axes(document).y.limits
    assert high == 2 and low < 0.1


def test_major_and_minor_ticks_in_plain_words(panel, document) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "y"))
    form = panel.axis_form
    assert form.major.currentData() == "auto" and form.major_value.isHidden()
    _choose(form.major, "step")
    assert not form.major_value.isHidden()
    _enter(form.major_value, "0.25")
    assert _axes(document).y.major_step == 0.25

    _choose(form.minor, "count")
    form.count.setValue(4)
    assert _axes(document).y.minor_divisions == 5  # four ticks, five parts
    assert form.count.value() == 4

    _choose(form.major, "values")
    _enter(form.major_value, "0, 0.5, 1")
    assert _axes(document).y.ticks == [0.0, 0.5, 1.0]
    assert _axes(document).y.major_step is None
    _enter(form.tick_labels, "none, half, full")
    assert _axes(document).y.tick_labels == ["none", "half", "full"]

    _choose(form.major, "auto")
    y = _axes(document).y
    assert y.ticks is None and y.tick_labels is None and y.major_step is None
    _choose(form.minor, "off")
    assert not _axes(document).y.minor_ticks


def test_a_tick_step_that_gives_too_many_ticks_is_refused(panel, document) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "x"))
    form = panel.axis_form
    _choose(form.major, "step")
    _enter(form.major_value, "0.001")  # the automatic range spans about 10
    assert _axes(document).x.major_step is None
    assert "at most 50" in panel._error.text()

    _enter(form.low, "0")
    _enter(form.high, "10000")
    _choose(form.major, "step")  # the form shows the model again after a change
    _enter(form.major_value, "500")
    assert _axes(document).x.major_step == 500
    _enter(form.high, "1000000")  # the step stays, so the range is refused
    assert _axes(document).x.limits == (0.0, 10_000.0)
    assert "at most 50" in panel._error.text()


def test_scale_choices_and_their_extra_rows(panel, document) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "x"))
    form = panel.axis_form
    assert form.linthresh.isHidden()
    _choose(form.scale, "symlog")
    assert not form.linthresh.isHidden()
    _enter(form.linthresh, "0.5")
    assert _axes(document).x.symlog_linthresh == 0.5
    _choose(form.scale, "log")
    _choose(form.minor, "count")
    assert not form.minor_hint.isHidden()  # a count needs a fixed major step
    _choose(form.major, "step")
    _enter(form.major_value, "2")
    assert form.minor_hint.isHidden()


def test_numbers_typed_with_decimal_commas(panel, document) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "y"))
    form = panel.axis_form
    _enter(form.low, "−0,5")
    _enter(form.high, "1,5")
    assert _axes(document).y.limits == (-0.5, 1.5)
    _choose(form.major, "values")
    _enter(form.major_value, "0; 0,5; 1")
    assert _axes(document).y.ticks == [0.0, 0.5, 1.0]


def test_a_wrong_number_is_reported(panel, document) -> None:
    document.select(axis_id(_axes(document).id, "x"))
    _enter(panel.axis_form.label_size, "big")
    assert "not a number" in panel.error
    _enter(panel.axis_form.label_size, "11")
    assert _axes(document).x.label_size == 11 and panel._error.isHidden()


def test_undo_shows_the_old_values(panel, document) -> None:
    axes = _axes(document)
    document.select(axis_id(axes.id, "x"))
    _enter(panel.axis_form.label, "Time")
    document.undo()
    assert panel.axis_form.label.text() == "$t$"
    document.push(SetField(axes.id, ("x", "label"), "Zeit"))
    assert panel.axis_form.label.text() == "Zeit"


def test_clicking_the_numbers_of_an_axis_selects_it(window, document) -> None:
    preview: Preview = window.preview
    ax = preview._figure.axes[0]
    renderer = preview._figure.canvas.get_renderer()
    low, high = ax.get_xlim()
    tick = next(
        t
        for t in ax.xaxis.get_major_ticks()
        if t.label1.get_text() and low <= t.get_loc() <= high
    )
    box = tick.label1.get_window_extent(renderer)
    point = preview._to_widget((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
    assert preview.object_at(point) == axis_id(_axes(document).id, "x")
    box = ax.yaxis.label.get_window_extent(renderer)
    point = preview._to_widget((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
    assert preview.object_at(point) == axis_id(_axes(document).id, "y")
    inside = preview._to_widget(ax.bbox.x0 + 5, ax.bbox.y1 - 5)
    assert preview.object_at(inside) != axis_id(_axes(document).id, "x")

    document.select(axis_id(_axes(document).id, "x"))
    assert preview.selection_rect() is not None
    assert not window.delete_action.isEnabled()  # an axis is not deleted
    assert window.outline.currentItem().text(0).lower().startswith("panel")
