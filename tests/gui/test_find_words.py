"""Finding what the examples use (U12): every kind of element in the twelve
examples is found in the command palette under words a person would try, and
the empty property panel says where to look."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QKeySequence

from figscribe.examples import gallery
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.palette import Entry, matching
from figscribe.model import loads

KINDS = {
    # model kind: (words to try, the entry that must come up)
    "line": (["line plot", "curve", "trace"], "Line"),
    "scatter": (["scatter", "markers", "dots"], "Points"),
    "errorbar": (["errorbar", "uncertainty", "sigma"], "Error bars"),
    "histogram": (["histogram", "bins", "distribution"], "Histogram"),
    "allan": (["allan", "stability", "adev"], "Allan deviation"),
    "colormesh": (["color mesh", "heatmap", "colormap"], "Color mesh"),
    "image": (["image", "picture", "matrix"], "Image"),
    "fit": (["fit", "regression", "curve fit"], "Add Fit…"),
    "residual": (["residuals", "least squares"], "Add Fit…"),
    "span": (["shaded", "band", "region", "highlight", "interval"], "Shaded x range"),
    "refline": (["reference", "threshold", "marker line"], "Vertical line"),
    "annotation": (["note", "annotation", "callout", "arrow", "text"], "Add Note…"),
}
"""What an artist of the model is called by someone who looks for it."""

OTHER = [
    (["subplot", "inset", "zoom"], "Inset"),
    (["csv", "load", "table"], "Import Data…"),
    (["tab", "page"], "Add Figure"),
]
"""A panel, data and a figure too."""


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.show()
    return win


def _found(entries: list[Entry], word: str, text: str) -> bool:
    return any(e.text == text for e in matching(entries, word))


def test_every_kind_in_the_examples_has_words_to_find_it_by() -> None:
    used = set()
    for example in gallery():
        project = loads(example.project_file.read_text(encoding="utf-8"))
        used |= {a.kind for f in project.figures for x in f.axes for a in x.artists}
    assert used <= set(KINDS), f"words for {sorted(used - set(KINDS))} are missing"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_kind_is_found_under_the_words_a_person_tries(window, kind: str) -> None:
    entries = window.palette_entries()
    words, text = KINDS[kind]
    for word in words:
        assert _found(entries, word, text), f"{word!r} does not find {text!r}"


@pytest.mark.parametrize(("words", "text"), OTHER)
def test_a_panel_data_and_a_figure_are_found_too(window, words, text) -> None:
    entries = window.palette_entries()
    for word in words:
        assert _found(entries, word, text), f"{word!r} does not find {text!r}"


def test_a_word_in_the_name_comes_before_a_synonym(window) -> None:
    window.document.select(window.document.figure.axes[0].artists[0].id)
    entries = window.palette_entries()
    assert matching(entries, "histogram")[0].text == "Histogram"
    found = [e.text for e in matching(entries, "band")]
    assert found[0] == "Error band"  # by its name
    assert "Shaded x range" in found[1:]  # by a synonym, after it


def test_the_arrow_of_a_note_is_found_with_a_note_selected(window) -> None:
    from figscribe.commands import InsertItem
    from figscribe.model import Annotation

    note = Annotation(text="x", position=(0.5, 0.5), coords="axes")
    window.document.push(InsertItem(window.document.figure.axes[0].id, "artists", note))
    window.document.select(note.id)
    entries = window.palette_entries()
    assert matching(entries, "arrow")[0].text == "Arrow to"


def test_a_setting_is_found_by_what_it_does(window) -> None:
    plot = window.document.figure.axes[0].artists[0]
    window.document.select(plot.id)
    entries = window.palette_entries()
    for word, caption in (
        ("downsample", "Fewer points"),
        ("average", "Fewer points"),
        ("ribbon", "Error band"),
        ("dashed", "Line style"),
    ):
        assert _found(entries, word, caption), f"{word!r} does not find {caption!r}"


def test_the_empty_panel_says_where_to_look(window) -> None:
    window.document.select(None)
    hints = [
        label.text()
        for label in window.properties.findChildren(type(window._project_name))
        if label.objectName() == "hint"
    ]
    shortcut = QKeySequence("Ctrl+K").toString(QKeySequence.SequenceFormat.NativeText)
    assert any(shortcut in text and "Select" in text for text in hints), hints
