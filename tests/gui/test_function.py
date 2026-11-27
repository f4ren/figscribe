"""Drawing a function from the window (F15)."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.outline import ID_ROLE
from figscribe.model import FunctionPlot, dumps


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.show()
    qtbot.waitExposed(win)
    return win


def _add(window: MainWindow, text: str) -> FunctionPlot:
    window.ask_name = lambda title, prompt, current: text
    window.function_action.trigger()
    return window.document.figure.axes[0].artists[-1]


def _type(window: MainWindow, line, text: str) -> None:
    line.setText(text)
    line.editingFinished.emit()


def test_it_is_inserted_from_the_menu_and_set_in_the_panel(
    window: MainWindow,
) -> None:
    made = _add(window, "a * exp(-x / tau)")
    assert isinstance(made, FunctionPlot) and window.preview.error is None
    assert window.document.selected == made.id
    panel = window.properties
    assert list(panel.editors[("parameters",)].lines) == ["a", "tau"]
    _type(window, panel.editors[("parameters",)].lines["tau"], "3,5")
    function = window.document.figure.axes[0].artists[-1]
    assert function.parameters == {"a": 1.0, "tau": 3.5}

    _type(window, panel.editors[("expression",)].line, "a * x + c")
    function = window.document.figure.axes[0].artists[-1]
    assert function.parameters == {"a": 1.0, "c": 1.0}
    assert list(window.properties.editors[("parameters",)].lines) == ["a", "c"]
    window.document.undo()  # the formula and its values, one step
    function = window.document.figure.axes[0].artists[-1]
    assert (function.expression, function.parameters["tau"]) == (
        "a * exp(-x / tau)",
        3.5,
    )


def test_a_formula_that_cannot_be_read_is_told(window: MainWindow) -> None:
    errors = []
    window.show_error = lambda title, why: errors.append(str(why))
    window.ask_name = lambda title, prompt, current: "a +"
    before = dumps(window.document.project)
    window.function_action.trigger()
    assert errors and "cannot be read" in errors[0]
    assert dumps(window.document.project) == before

    _add(window, "x")
    line = window.properties.editors[("expression",)].line
    _type(window, line, "open('x')")
    assert window.document.figure.axes[0].artists[-1].expression == "x"


def test_it_is_offered_in_the_panels_menu_and_found(window: MainWindow) -> None:
    panel = window.document.figure.axes[0]
    texts = [a.text() for a in window.outline.context_menu(panel.id).actions()]
    assert "Add function…" in texts
    found = [e.text for e in window.palette_entries() if "theory" in e.keywords]
    assert found == ["Function…"]
    made = _add(window, "x")
    items = window.outline.item_for(made.id)
    assert items.data(0, ID_ROLE) == made.id and "f(x) = x" in items.text(0)


def test_a_long_formula_is_shown_from_its_start(window: MainWindow) -> None:
    _add(window, "a * exp(-(x - mu)**2 / (2 * sigma**2))")
    assert window.properties.editors[("expression",)].line.cursorPosition() == 0
