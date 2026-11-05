"""The toolbar's buttons that add things (decision 0055): each shows what it
makes, they stay reachable in a narrow window, and the menus they open are
the ones a person looks in."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.palette import matching, menu_entries
from figscribe.gui.plotdialog import KINDS, PlotDialog
from figscribe.model import AllanDeviationPlot, Histogram, ImagePlot

ADDING = ["Data", "Figure", "Panel", "Plot", "Fit", "Note", "Reference"]


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.show()
    return win


def _buttons(window: MainWindow) -> dict[str, QToolButton]:
    bar = window.toolbar
    found = {}
    for action in bar.actions():
        widget = bar.widgetForAction(action)
        if isinstance(widget, QToolButton) and widget.text() in ADDING:
            found[widget.text()] = widget
    return found


def _overflowing(window: MainWindow) -> bool:
    button = window.toolbar.findChild(QToolButton, "qt_toolbar_ext_button")
    return button is not None and button.isVisible()


def test_the_adding_buttons_come_in_the_order_of_a_figure(window) -> None:
    assert list(_buttons(window)) == ADDING


def _picture(icon):
    return icon.pixmap(16, 16).toImage()


def test_every_adding_button_shows_what_it_makes(window) -> None:
    """Not the same plus on all of them: each has a picture of its own, and
    none is the picture of the start page's button."""
    pictures = {n: _picture(b.icon()) for n, b in _buttons(window).items()}
    for name, picture in pictures.items():
        assert not picture.isNull() and picture.hasAlphaChannel(), name
        for other, image in pictures.items():
            assert name == other or picture != image, f"{name} looks like {other}"
        assert picture != _picture(window.home_action.icon()), name


def _wordy(window: MainWindow) -> set[Qt.ToolButtonStyle]:
    return {button.toolButtonStyle() for button in window.toolbar.wordy}


def test_the_words_go_exactly_when_they_no_longer_fit(window, qtbot) -> None:
    bar = window.toolbar
    needed = bar.words_width()
    window.resize(needed + 20, 700)
    qtbot.wait(50)
    if bar.width() < needed:
        pytest.skip("the screen is narrower than the toolbar with its words")
    assert _wordy(window) == {Qt.ToolButtonStyle.ToolButtonTextBesideIcon}
    window.resize(needed - 20, 700)
    qtbot.wait(50)
    assert _wordy(window) == {Qt.ToolButtonStyle.ToolButtonIconOnly}
    window.resize(needed + 20, 700)
    qtbot.wait(50)
    assert _wordy(window) == {Qt.ToolButtonStyle.ToolButtonTextBesideIcon}


def test_a_narrow_window_shows_icons_alone_and_loses_none(window, qtbot) -> None:
    window.resize(window.minimumSizeHint().width(), 700)
    qtbot.wait(50)
    for name, button in _buttons(window).items():
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly, name
        assert button.toolTip(), name  # the words are still there, as a tip
    assert not _overflowing(window)


def test_the_reference_menu_holds_lines_and_ranges(window) -> None:
    # The action is kept: before PySide6 6.12 its menu is gone with it.
    action = next(a for a in window.menuBar().actions() if a.text() == "&Insert")
    titles = [a.text().replace("&", "") for a in action.menu().actions()]
    assert "Add Reference" in titles
    assert not any("Line or Range" in t for t in titles)
    reference = _buttons(window)["Reference"]
    assert reference.menu() is window.marking_menu
    assert [a.text() for a in window.marking_menu.actions()] == [
        "Vertical line",
        "Horizontal line",
        "Shaded x range",
        "Shaded y range",
    ]


def test_the_three_menu_buttons_open_their_menu_alike(window) -> None:
    """Panel, Plot and Reference all show their menu on a click, with the
    arrow in the same place: no split button among them."""
    buttons = _buttons(window)
    for name in ("Panel", "Plot", "Reference"):
        assert buttons[name].popupMode() == (
            QToolButton.ToolButtonPopupMode.InstantPopup
        ), name
    entries = [a.text() for a in buttons["Plot"].menu().actions()]
    assert entries[0] == "Add &Plot…" and entries[1] == ""
    assert entries[2:] == list(KINDS)


def test_every_entry_of_the_adding_menus_has_a_picture_of_its_own(window) -> None:
    for menu in (window.panel_menu, window.marking_menu, window.plot_menu):
        pictures = []
        for action in menu.actions():
            picture = _picture(action.icon())
            assert not picture.isNull(), action.text()
            pictures.append(picture)
        for i, one in enumerate(pictures):
            assert all(one != other for other in pictures[:i]), menu.title()


@pytest.mark.parametrize(
    ("name", "kind"),
    [("Histogram", Histogram), ("Allan deviation", AllanDeviationPlot)],
)
def test_a_kind_chosen_from_the_menu_is_chosen_in_the_dialog(
    window, name, kind
) -> None:
    seen = {}

    def look(dialog: PlotDialog) -> bool:
        seen["kind"] = dialog.kind
        return False

    window.run_dialog = look
    next(a for a in window.plot_menu.actions() if a.text() == name).trigger()
    assert seen["kind"] is kind


def test_the_button_itself_starts_as_before(window) -> None:
    seen = {}

    def look(dialog: PlotDialog) -> bool:
        seen["kind"] = dialog.kind
        return False

    window.run_dialog = look
    window.plot_action.trigger()
    assert seen["kind"] is not None
    assert seen["kind"] not in (Histogram, AllanDeviationPlot)


def test_a_kind_that_the_data_cannot_make_falls_back(window, qtbot) -> None:
    """Without 2-D data an image cannot be made: the dialog opens as usual."""
    columns = window.document.column_choices()
    dialog = PlotDialog(columns, arrays=[], kind="Image")
    qtbot.addWidget(dialog)
    assert not dialog.tiles["Image"].isEnabled()
    assert dialog.kind is not ImagePlot
    assert dialog.tiles["Line"].isChecked() or dialog.tiles["Error bars"].isChecked()


def test_the_kinds_are_found_from_the_command_palette(window) -> None:
    entries = menu_entries(window.menuBar())
    for word, text in (
        ("histogram", "Histogram"),
        ("allan", "Allan deviation"),
        ("mesh", "Color mesh"),
    ):
        found = matching(entries, word)
        assert any(e.text == text for e in found), word
    shaded = matching(entries, "shaded")
    assert {e.text for e in shaded} >= {"Shaded x range", "Shaded y range"}
    assert all("Reference" in e.where for e in shaded)
