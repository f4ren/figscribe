"""Finding the settings of an axis (U12): log, limits, ticks and the rest are
found by the words a person tries, also when a panel or a plot is selected and
the axis form is not open; running one opens that axis's form on it."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from figscribe.commands import SetField
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.axisform import AXIS_TITLES, axis_settings
from figscribe.gui.document import axis_id
from figscribe.gui.palette import Entry, matching
from figscribe.model import AxisSpec


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _panel(window: MainWindow):
    return window.document.figure.axes[0]


def _axis_entry(entries: list[Entry], word: str, text: str, axis: str) -> Entry | None:
    """The entry `text` of the named axis that `word` finds."""
    return next(
        (
            e
            for e in matching(entries, word)
            if e.text == text and f" · {AXIS_TITLES[axis]} ·" in e.where
        ),
        None,
    )


WORDS = [
    ("log", "Type"),
    ("logarithmic", "Type"),
    ("symlog", "Type"),
    ("limits", "From"),
    ("xlim", "From"),
    ("range", "From"),
    ("ticks", "Major ticks"),
    ("tick spacing", "Major ticks"),
    ("minor", "Minor ticks"),
    ("tick labels", "Major ticks"),
    ("prefix", "Show values in"),
    ("unit", "Unit"),
    ("labelpad", "Label distance (pt)"),
]


@pytest.mark.parametrize(("word", "text"), WORDS)
@pytest.mark.parametrize("axis", ["x", "y"])
def test_a_panel_selected_offers_the_settings_of_its_axes(
    window, word: str, text: str, axis: str
) -> None:
    window.document.select(_panel(window).id)
    entry = _axis_entry(window.palette_entries(), word, text, axis)
    assert entry is not None, f"{word!r} does not find {text} of the {axis} axis"
    assert entry.where.startswith("Setting · ")


def test_a_plot_selected_offers_the_axes_of_its_panel_too(window) -> None:
    window.document.select(_panel(window).artists[0].id)
    entries = window.palette_entries()
    assert _axis_entry(entries, "log", "Type", "x") is not None
    assert _axis_entry(entries, "log", "Type", "y") is not None


def test_nothing_is_offered_without_a_panel(window) -> None:
    window.document.select(window.document.figure.id)
    entries = window.palette_entries()
    assert not [e for e in matching(entries, "symlog") if "axis" in e.where]


def test_the_right_y_axis_is_offered_only_when_there_is(window) -> None:
    panel = _panel(window)
    window.document.select(panel.id)
    assert panel.y_right is None
    entries = window.palette_entries()
    assert _axis_entry(entries, "log", "Type", "y_right") is None
    window.document.push(SetField(panel.id, ("y_right",), AxisSpec()))
    entries = window.palette_entries()
    assert _axis_entry(entries, "log", "Type", "y_right") is not None


def test_running_one_opens_that_axis_on_the_setting(window) -> None:
    window.document.select(_panel(window).id)
    entry = _axis_entry(window.palette_entries(), "log", "Type", "y")
    entry.run()
    assert window.document.selected == axis_id(_panel(window).id, "y")
    assert window.properties.sections["Scale"].expanded
    focused = QApplication.focusWidget()
    widget = window.properties.axis_form.scale
    assert focused is widget or widget.isAncestorOf(focused)


def test_with_an_axis_selected_its_own_settings_have_the_words_too(window) -> None:
    panel = _panel(window)
    window.document.select(axis_id(panel.id, "x"))
    entries = window.palette_entries()
    for word, text in WORDS:
        found = [e for e in matching(entries, word) if e.text == text]
        assert found, f"{word!r} does not find {text}"
    own = [e for e in entries if e.text == "Type" and e.where == "Setting · Scale"]
    assert len(own) == 1
    # the other axis of the panel is a step away; this one is not offered twice
    assert _axis_entry(entries, "log", "Type", "x") is None
    assert _axis_entry(entries, "log", "Type", "y") is not None


def test_a_setting_that_waits_for_another_is_not_offered(window) -> None:
    """ "Linear within ±" is there for a symmetric log axis only."""
    panel = _panel(window)
    window.document.select(axis_id(panel.id, "x"))
    assert not [e for e in window.palette_entries() if e.text == "Linear within ±"]
    window.document.push(SetField(panel.id, ("x", "scale"), "symlog"))
    assert [e for e in window.palette_entries() if e.text == "Linear within ±"]


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"scale": "symlog"},
        {"ticks": [1.0, 2.0]},
        {"major_step": 5.0},
    ],
)
def test_the_list_of_axis_settings_is_what_the_form_shows(window, change) -> None:
    """The entries for a panel's axes come from a list; the form is the truth."""
    panel = _panel(window)
    window.document.push(SetField(panel.id, ("x",), AxisSpec(**change)))
    window.document.select(axis_id(panel.id, "x"))
    shown = [
        (title, caption)
        for caption, title, _ in window.properties.settings()
        if title in {"Label", "Scale", "Ticks"}
    ]
    assert axis_settings(panel.x) == shown
