"""Smoothing in the property panel and for the assistant (decision 0083)."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import Document, MainWindow
from figscribe.model import Smoothing
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
