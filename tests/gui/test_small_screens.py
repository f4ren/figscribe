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

KNOWN: dict[str, str] = {}
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


# --- the fit dialog scrolls when the screen is small ---------------------------


def _fit_dialog(qtbot, example: Path, monkeypatch, room: int) -> FitDialog:
    """The dialog as it opens on a screen that leaves `room` points of height."""
    from figscribe.gui import fitdialog

    monkeypatch.setattr(fitdialog, "screen_room", lambda: room)
    dialog = _make("fit", example)
    qtbot.addWidget(dialog)
    return dialog


def _bottom_is_reachable(dialog: FitDialog) -> bool:
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    return dialog.rect().contains(ok.mapTo(dialog, ok.rect().bottomRight()))


def test_the_fit_dialog_shows_everything_where_there_is_room(
    qtbot, themed, example: Path, monkeypatch
) -> None:
    dialog = _fit_dialog(qtbot, example, monkeypatch, room=2000)
    opens_at = dialog.height()  # Qt cuts a window to the screen when it shows it
    assert opens_at >= dialog._settings.sizeHint().height()
    dialog.show()
    dialog.resize(dialog.width(), opens_at)
    qtbot.wait(20)
    assert not dialog.scroll.verticalScrollBar().isVisible()
    assert dialog.residuals.isVisibleTo(dialog) and _bottom_is_reachable(dialog)


def test_the_fit_dialog_scrolls_its_middle_where_there_is_not(
    qtbot, themed, example: Path, monkeypatch
) -> None:
    dialog = _fit_dialog(qtbot, example, monkeypatch, room=560)
    assert dialog.height() <= 560
    dialog.show()
    bar = dialog.scroll.verticalScrollBar()
    assert bar.isVisible() and bar.maximum() > 0
    # the buttons stay in view, and the last setting can be scrolled to
    assert _bottom_is_reachable(dialog)
    bar.setValue(bar.maximum())
    visible = dialog.scroll.viewport().rect()
    last = dialog.residuals
    assert visible.contains(last.mapTo(dialog.scroll.viewport(), last.rect().center()))


def test_the_model_list_stays_put_while_the_middle_scrolls(
    qtbot, themed, example: Path, monkeypatch
) -> None:
    dialog = _fit_dialog(qtbot, example, monkeypatch, room=560)
    dialog.show()
    first = dialog.models.buttons()[0]
    before = first.mapTo(dialog, first.rect().topLeft())
    bar = dialog.scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert first.mapTo(dialog, first.rect().topLeft()) == before


def test_the_scrolling_settings_have_the_dialogs_white_ground(
    qtbot, themed, example: Path, monkeypatch
) -> None:
    """Inside a scroll area the ground is the window's grey unless told."""
    from figscribe.gui import theme

    dialog = _fit_dialog(qtbot, example, monkeypatch, room=560)
    dialog.show()
    viewport = dialog.scroll.viewport()
    spot = viewport.mapTo(dialog, viewport.rect().center())
    color = dialog.grab().toImage().pixelColor(spot.x(), spot.y() + 150)
    assert color.name().upper() == theme.SURFACE
