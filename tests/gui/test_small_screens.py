"""Small screens: B7.5 of the roadmap.

The main window is meant to work at 1024 × 700 points. A dialog is held to the
smallest screen still sold on laptops, 1366 × 768, less what the system keeps
(the menu bar or the task bar, and the title bar)."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.assistant.chat import Provider
from figscribe.gui import Document
from figscribe.gui.assistantdialog import AssistantDialog
from figscribe.gui.fitdialog import FitDialog
from figscribe.gui.importdialog import ImportDialog
from figscribe.gui.plotdialog import PlotDialog
from figscribe.model import ColumnRef

from .test_every_field import OBJECTS

ROOM = (1366 - 40, 768 - 110)
"""What a dialog can have of the smallest laptop screen."""

KNOWN = {
    "fit": "its height grows with the model: a polynomial has up to ten "
    "parameters (roadmap B7.5)",
}
"""Dialogs that are too big, with why; the test says when one is fixed."""


def _make(name: str, example: Path):
    document = Document.open(example)
    data = document.figure.axes[0].artists[0]
    source = document.project.sources[0]
    if name == "fit":
        return FitDialog(data, document.data)
    if name == "import":
        return ImportDialog(example.parent / "scan.csv", example.parent)
    if name == "plot":
        columns = [(c, ColumnRef(source=source.id, column=c)) for c in source.columns]
        return PlotDialog(columns, data=document.data)
    return AssistantDialog(Provider("anthropic", "claude-sonnet-5-5"))


@pytest.mark.parametrize("name", ["fit", "import", "plot", "assistant"])
def test_a_dialog_fits_a_small_screen(qtbot, themed, example: Path, name: str) -> None:
    dialog = _make(name, example)
    qtbot.addWidget(dialog)
    dialog.show()
    size = dialog.minimumSizeHint()
    fits = size.width() <= ROOM[0] and size.height() <= ROOM[1]
    if name in KNOWN:
        assert not fits, f"{name} fits now: take it off KNOWN ({KNOWN[name]})"
        return
    assert fits, (
        f"{name} needs {size.width()} × {size.height()}; "
        f"the smallest laptop screen leaves {ROOM[0]} × {ROOM[1]}"
    )


# --- the main window at 1024 × 700 -----------------------------------------------


@pytest.fixture(scope="module")
def project_file(tmp_path_factory) -> Path:
    from .everything import build

    return build(tmp_path_factory.mktemp("everything"))


def test_the_window_can_be_as_small_as_a_small_screen(
    qtbot, themed, project_file: Path
) -> None:
    from figscribe.gui import MainWindow

    window = MainWindow(Document.open(project_file))
    qtbot.addWidget(window)
    window.resize(1024, 700)
    window.show()
    hint = window.minimumSizeHint()
    assert hint.width() <= 1024 and hint.height() <= 700, hint
    assert (window.width(), window.height()) == (1024, 700)


@pytest.mark.slow
@pytest.mark.parametrize("name", list(OBJECTS))
def test_the_panel_clips_nothing_at_1024_by_700(
    qtbot, themed, project_file: Path, name: str
) -> None:
    """The property panel never scrolls sideways, so what does not fit would be
    cut off without a way to reach it: every control must lie inside it."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QToolButton, QWidget

    from figscribe.gui import MainWindow

    window = MainWindow(Document.open(project_file))
    qtbot.addWidget(window)
    window.resize(1024, 700)
    window.show()
    panel = window.properties
    window.document.select(OBJECTS[name](window.document.project))
    for section in panel.sections.values():  # open what is folded, as a person
        if isinstance(section.header, QToolButton) and not section.expanded:
            section.header.click()
    form = panel.widget()
    edge = panel.viewport().width()
    cut = []
    for child in form.findChildren(QWidget):
        if not child.isVisibleTo(form) or child.width() == 0:
            continue
        right = child.mapTo(form, QPoint(child.width(), 0)).x()
        if right > edge + 1:
            cut.append(f"{type(child).__name__} {child.objectName()!r} to {right}")
    assert not cut, f"{name}: panel is {edge} wide; " + "; ".join(cut[:5])
