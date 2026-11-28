"""Smoothing in the property panel and for the assistant (decision 0083)."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.commands import SetField
from figscribe.gui import Document, MainWindow
from figscribe.model import Baseline, Peaks, Smoothing
from figscribe.tools.operations import Toolbox, ToolError
from figscribe.tools.workspace import ProjectWorkspace
from tests.test_process import made


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    project, _, _ = made(tmp_path)
    document = Document(project, tmp_path / "p.figscribe")
    win = MainWindow(document)
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    return win


def _plot(window):
    return window.document.figure.axes[0].artists[0]


def _editor(window, *path):
    window.document.select(_plot(window).id)
    return window.properties.editors[path].widget


def _choose(box, text: str) -> None:
    box.setCurrentText(text)
    box.activated.emit(box.currentIndex())


def test_smoothing_is_turned_on_and_set_in_the_panel(window) -> None:
    box = _editor(window, "smoothing")
    box.click()
    assert _plot(window).smoothing == Smoothing()
    method = _editor(window, "smoothing", "method")
    assert [method.itemText(i) for i in range(method.count())] == [
        "Savitzky–Golay",
        "moving average",
    ]
    line = _editor(window, "smoothing", "window")
    line.setText("7")
    line.editingFinished.emit()
    assert _plot(window).smoothing.window == 7
    _choose(_editor(window, "smoothing", "method"), "moving average")
    window.document.select(_plot(window).id)
    assert not _editor(window, "smoothing", "order").isEnabled()
    # The reduction's own choices are as they were.
    _editor(window, "reduction").click()
    drawn = _editor(window, "reduction", "method")
    assert drawn.itemText(0) == "mean of n rows"


def test_a_window_that_cannot_be_is_told_and_changes_nothing(window) -> None:
    _editor(window, "smoothing").click()
    for typed, why in (("8", "odd"), ("99", "99 points")):
        line = _editor(window, "smoothing", "window")
        line.setText(typed)
        line.editingFinished.emit()
        assert why in window.properties.error
        assert _plot(window).smoothing.window == 11


def test_the_assistant_smooths_through_the_same_command(tmp_path: Path) -> None:
    project, _, plot = made(tmp_path)
    workspace = ProjectWorkspace(project, tmp_path)
    tools = Toolbox(workspace)
    call = {"object_id": plot.id, "path": ["smoothing"], "value": {"window": 5}}
    tools.call("set_field", call)
    assert workspace.project.figures[0].axes[0].artists[0].smoothing.window == 5
    tools.call("set_field", call | {"path": ["smoothing", "window"], "value": 7})
    assert workspace.project.figures[0].axes[0].artists[0].smoothing.window == 7
    with pytest.raises(ToolError, match="99 points"):
        tools.call("set_field", call | {"value": {"window": 99}})


def test_normalising_is_chosen_beside_the_unit(window) -> None:
    box = _editor(window, "normalize")
    offered = [box.itemText(i) for i in range(box.count())]
    assert offered == ["no", "maximum = 1", "area = 1"]
    _choose(box, "maximum = 1")
    assert _plot(window).normalize == "max"
    window.document.select(_plot(window).id)
    shown = list(window.properties.editors)
    assert shown.index(("normalize",)) == shown.index(("y_conversion",)) + 1
    _choose(_editor(window, "normalize"), "no")
    assert _plot(window).normalize is None


def test_a_method_that_needs_a_lower_order_gets_one(window) -> None:
    _editor(window, "smoothing").click()
    _choose(_editor(window, "smoothing", "method"), "moving average")
    line = _editor(window, "smoothing", "window")
    line.setText("3")
    line.editingFinished.emit()
    _choose(_editor(window, "smoothing", "method"), "Savitzky–Golay")
    assert _plot(window).smoothing == Smoothing(window=3, order=2)


def test_the_reason_names_the_setting(window) -> None:
    _editor(window, "smoothing").click()
    line = _editor(window, "smoothing", "order")
    line.setText("11")
    line.editingFinished.emit()
    assert not window.properties.error.startswith("Draw")


def test_smoothing_a_short_series_can_be_turned_on(window) -> None:
    plot = _plot(window)
    window.document.push(SetField(plot.id, ("left_out",), list(range(8, 20))))
    _editor(window, "smoothing").click()
    assert _plot(window).smoothing.window == 7


def test_a_baseline_and_its_ranges_in_the_panel(window) -> None:
    _editor(window, "baseline").click()
    assert _plot(window).baseline == Baseline()
    assert not _editor(window, "baseline", "degree").isEnabled()
    line = _editor(window, "baseline", "ranges")
    assert line.placeholderText() == "every point"
    line.setText("0 to 5, 15 to 19")
    line.editingFinished.emit()
    assert _plot(window).baseline.ranges == [(0.0, 5.0), (15.0, 19.0)]
    window.document.select(_plot(window).id)
    assert _editor(window, "baseline", "ranges").text() == "0 to 5, 15 to 19"
    _choose(_editor(window, "baseline", "shape"), "polynomial")
    assert _editor(window, "baseline", "degree").isEnabled()
    line = _editor(window, "baseline", "ranges")
    line.setText("nonsense")
    line.editingFinished.emit()
    assert "such as 0 to 5" in window.properties.error
    line.setText("0,5 to 4,5; 15 to 19")  # decimal commas
    line.editingFinished.emit()
    assert _plot(window).baseline.ranges == [(0.5, 4.5), (15.0, 19.0)]
    line = _editor(window, "baseline", "ranges")
    line.setText("")
    line.editingFinished.emit()
    assert _plot(window).baseline.ranges == []


def test_peaks_in_the_panel(window) -> None:
    _editor(window, "peaks").click()
    assert _plot(window).peaks == Peaks()
    line = _editor(window, "peaks", "prominence")
    assert line.placeholderText() == "a tenth of the span"
    line.setText("0.5")
    line.editingFinished.emit()
    assert _plot(window).peaks.prominence == 0.5
    _editor(window, "peaks", "labels").click()
    window.document.select(_plot(window).id)
    assert not _editor(window, "peaks", "decimals").isEnabled()
    _editor(window, "peaks").click()
    assert _plot(window).peaks is None


def test_a_peaks_label_is_no_note_of_its_own(window, qtbot) -> None:
    plot = _plot(window)
    window.document.push(SetField(plot.id, ("peaks",), Peaks(prominence=0.05)))
    window.show()
    qtbot.waitExposed(window)
    preview = window.preview
    ax = preview._figure.axes[0]
    label = ax.texts[0]
    box = label.get_window_extent(preview._figure.canvas.get_renderer())
    point = preview._to_widget(*box.get_points().mean(axis=0))
    assert preview._note_at(point) is None
    found = preview.text_at(point)
    assert found is None or found.path != ("text",)
    preview.context_menu(point)  # no crash
    before = window.document.project.model_dump_json()
    preview.move_note(label.get_gid(), 10, 10)
    assert window.document.project.model_dump_json() == before


def test_one_stretch_may_be_typed_with_decimal_commas(window) -> None:
    _editor(window, "baseline").click()
    for typed, ranges in (
        ("0,5 to 4,5", [(0.5, 4.5)]),
        ("0 to 5,15 to 19", [(0.0, 5.0), (15.0, 19.0)]),
    ):
        line = _editor(window, "baseline", "ranges")
        line.setText(typed)
        line.editingFinished.emit()
        assert _plot(window).baseline.ranges == ranges
