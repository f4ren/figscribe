"""Finding a setting: the search above the property panel, and the command
palette (Ctrl+K) for menu actions and settings, operated by typing."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFormLayout

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.palette import CommandPalette, Entry, matching, menu_entries


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _shown_captions(window: MainWindow) -> list[str]:
    """The captions of the fields the panel shows now."""
    panel = window.properties
    found = []
    for section in panel.sections.values():
        if not section.isVisible():
            continue
        form = section.body.layout()
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item is not None and form.isRowVisible(row) and section.expanded:
                found.append(item.widget().text())
    return found


def _search(window: MainWindow, qtbot, text: str) -> None:
    search = window.properties.search
    search.clear()
    QTest.keyClicks(search, text)
    qtbot.waitUntil(lambda: not window.properties._filtering.isActive())


def test_the_search_keeps_only_the_fields_it_finds(window: MainWindow, qtbot) -> None:
    plot = window.document.figure.axes[0].artists[0]
    window.document.select(plot.id)
    everything = _shown_captions(window)
    _search(window, qtbot, "cap")
    assert _shown_captions(window) == ["Cap size (pt)"]
    _search(window, qtbot, "width")
    shown = _shown_captions(window)
    assert "Line width (pt)" in shown and "Error bar width (pt)" in shown
    assert "Marker" not in shown
    _search(window, qtbot, "legend")  # a section's title finds its fields
    assert _shown_captions(window) == ["Label"]
    QTest.keyClick(window.properties.search, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not window.properties._filtering.isActive())
    assert window.properties.search.text() == ""
    assert _shown_captions(window) == everything


def test_the_search_looks_in_the_tooltips_and_opens_folded_sections(
    window: MainWindow, qtbot
) -> None:
    window.document.select(window.document.figure.axes[0].artists[0].id)
    more = window.properties.sections["More"]
    assert not more.expanded
    _search(window, qtbot, "drawn on top")  # only in the tooltip
    assert _shown_captions(window) == ["Drawing order"]
    assert window.properties.sections["More"].expanded
    _search(window, qtbot, "")
    assert not window.properties.sections["More"].expanded  # as the user left it


def test_the_search_stays_while_another_object_is_selected(
    window: MainWindow, qtbot
) -> None:
    window.document.select(window.document.figure.id)
    _search(window, qtbot, "tick")
    shown = _shown_captions(window)
    assert shown and all("tick" in c.lower() for c in shown)
    window.document.select(window.document.figure.axes[0].artists[0].id)
    assert window.properties.search.text() == "tick"
    _search(window, qtbot, "xylophone")
    assert window.properties.matches == 0
    assert "No setting here matches" in window.properties._no_match.text()


def test_ctrl_f_puts_the_cursor_in_the_search(window: MainWindow) -> None:
    QTest.keyClick(window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.focusWidget() is window.properties.search


def test_palette_matching_puts_what_starts_with_the_word_first() -> None:
    entries = [
        Entry("Export Figure…", "File", lambda: None),
        Entry("Add Figure", "Insert", lambda: None),
        Entry("Figure size", "Setting", lambda: None),
    ]
    assert [e.text for e in matching(entries, "figure")] == [
        "Figure size",
        "Export Figure…",
        "Add Figure",
    ]
    assert [e.text for e in matching(entries, "add fig")] == ["Add Figure"]
    assert [e.text for e in matching(entries, "insert")] == ["Add Figure"]


def _palette(window: MainWindow, keys: str, *, down: int = 0) -> CommandPalette:
    """Open the palette with Ctrl+K, type `keys`, go `down` and press Enter."""
    opened: list[CommandPalette] = []

    def run(dialog) -> bool:
        opened.append(dialog)
        QTest.keyClicks(dialog.line, keys)
        for _ in range(down):
            QTest.keyClick(dialog.line, Qt.Key.Key_Down)
        QTest.keyClick(dialog.line, Qt.Key.Key_Return)
        return dialog.result() == dialog.DialogCode.Accepted

    window.run_dialog = run
    QTest.keyClick(window, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    return opened[0]


def test_the_palette_runs_a_menu_action(window: MainWindow) -> None:
    palette = _palette(window, "add figure")
    assert palette.chosen.text == "Add Figure"
    assert [f.name for f in window.document.project.figures] == ["Scan", "Figure 2"]
    assert not any("Find Setting or Action" in e.text for e in palette.entries)


def test_the_palette_goes_to_a_setting(window: MainWindow, qtbot) -> None:
    window.document.select(window.document.figure.axes[0].artists[0].id)
    _search(window, qtbot, "cap")  # a search that hides the setting looked for
    palette = _palette(window, "opacity")
    assert palette.chosen.where == "Setting · More"
    assert window.properties.search.text() == ""
    assert window.properties.sections["More"].expanded  # opened to show it
    focused = QApplication.focusWidget()
    caption, _, widget = next(
        s for s in window.properties.settings() if s[0] == "Opacity"
    )
    assert focused is widget or widget.isAncestorOf(focused)


def test_the_arrow_keys_choose_another_entry(window: MainWindow) -> None:
    palette = _palette(window, "add panel", down=1)
    assert palette.chosen is matching(palette.entries, "add panel")[1]
    assert len(window.document.figure.axes) == 2


def test_esc_elsewhere_leaves_the_search_alone(window: MainWindow, qtbot) -> None:
    """Esc clears the search only in it: in the preview it drops a zoom."""
    _search(window, qtbot, "tick")
    preview = window.preview
    preview.setFocus()
    preview.zoom(QPointF(preview.width() / 2, preview.height() / 2), 2.0)
    assert preview.view
    QTest.keyClick(preview, Qt.Key.Key_Escape)
    assert window.properties.search.text() == "tick"
    assert not preview.view  # the view is back at the model's ranges


def test_an_entry_of_a_submenu_runs_after_the_menus_were_read(
    window: MainWindow,
) -> None:
    """PySide6 before 6.12 made the actions of a submenu invalid once the
    palette had read the menus: running one raised "already deleted"."""
    import gc

    entries = menu_entries(window.menuBar())
    gc.collect()
    panels = len(window.document.figure.axes)
    (entry,) = [e for e in entries if e.text == "Panel to the right"]
    entry.run()
    assert len(window.document.figure.axes) == panels + 1
