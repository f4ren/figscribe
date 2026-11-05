"""Never lose work (roadmap E2, decision 0063): while a project has unsaved
changes it is written to a recovery file now and then; after a crash the next
start offers it."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from figscribe.commands import SetField
from figscribe.gui import MainWindow, recovery
from figscribe.gui.app import create_window
from figscribe.model import loads


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.show()
    return win


def _rename(window: MainWindow, name: str) -> None:
    figure = window.document.figure
    window.document.push(SetField(figure.id, ("name",), name))


def _file(window: MainWindow) -> Path:
    return recovery.recovery_file(window.document.path)


def test_a_changed_project_is_written_to_a_recovery_file(window) -> None:
    assert not _file(window).exists()
    window.autosave()
    assert not _file(window).exists(), "nothing changed, nothing to recover"
    _rename(window, "Changed")
    window.autosave()
    assert _file(window).name == "scan.figscribe.autosave"
    saved = loads(_file(window).read_text(encoding="utf-8"))
    assert saved.figures[0].name == "Changed"
    assert window.document.path.read_text() != _file(window).read_text()


def test_saving_and_closing_remove_it(window, qtbot) -> None:
    _rename(window, "Changed")
    window.autosave()
    window.document.save()
    window.autosave()
    assert not _file(window).exists()
    _rename(window, "Again")
    window.autosave()
    assert _file(window).exists()
    window.close()  # the project is not saved; the user said discard
    assert not _file(window).exists()


def test_a_timer_does_it_every_minute(window) -> None:
    assert window._autosave_timer.isActive()
    assert window._autosave_timer.interval() == recovery.INTERVAL_MS == 60_000


def _crash(window: MainWindow, name: str = "Unsaved") -> Path:
    """Leave a recovery file behind, as a crash does."""
    _rename(window, name)
    window.autosave()
    kept = _file(window)
    window.document.history.mark_clean()  # as if closed without a word
    window._autosave_timer.stop()
    return kept


def test_the_next_start_offers_the_recovery(qtbot, example: Path) -> None:
    first = create_window([str(example)])
    qtbot.addWidget(first)
    kept = _crash(first)
    now = time.time()
    os.utime(example, (now - 60, now - 60))
    os.utime(kept, (now, now))
    asked = []
    second = MainWindow()
    qtbot.addWidget(second)
    second.ask = lambda title, text: asked.append((title, text)) or True
    second.open_path(example)
    assert asked and "unsaved changes" in asked[0][1]
    assert second.document.figure.name == "Unsaved"
    assert not second.document.history.is_clean  # it can be saved
    assert second.document.path == example
    second.document.save()
    assert not kept.exists()


def test_declining_the_recovery_removes_it_and_opens_the_file(
    qtbot, example: Path
) -> None:
    first = create_window([str(example)])
    qtbot.addWidget(first)
    kept = _crash(first)
    now = time.time()
    os.utime(example, (now - 60, now - 60))
    os.utime(kept, (now, now))
    second = MainWindow()
    qtbot.addWidget(second)
    second.ask = lambda title, text: False
    second.open_path(example)
    assert second.document.figure.name != "Unsaved"
    assert second.document.history.is_clean
    assert not kept.exists()


def test_a_recovery_older_than_the_file_is_ignored(qtbot, example: Path) -> None:
    first = create_window([str(example)])
    qtbot.addWidget(first)
    kept = _crash(first)
    now = time.time()
    os.utime(example, (now, now))  # the project was saved after the recovery
    os.utime(kept, (now - 60, now - 60))
    second = MainWindow()
    qtbot.addWidget(second)
    second.ask = lambda title, text: pytest.fail("asked about an old recovery")
    second.open_path(example)
    assert second.document.figure.name != "Unsaved"
    assert not kept.exists()


def test_an_untitled_project_is_recovered_at_the_start(qtbot, example: Path) -> None:
    first = MainWindow()
    qtbot.addWidget(first)
    _rename(first, "Untitled work")
    first.autosave()
    kept = recovery.recovery_file(None)
    assert kept.parent == recovery.UNTITLED_FOLDER and kept.exists()
    first._autosave_timer.stop()
    first.document.history.mark_clean()
    second = MainWindow()
    qtbot.addWidget(second)
    second.ask = lambda title, text: True
    second.offer_recovery(None)
    assert second.document.figure.name == "Untitled work"
    assert second.document.path is None


def test_a_folder_that_cannot_be_written_is_not_an_error(window) -> None:
    _rename(window, "Changed")
    folder = window.document.path.parent
    folder.chmod(0o500)
    try:
        window.autosave()  # no exception, the work goes on
    finally:
        folder.chmod(0o700)


def test_a_clean_untitled_window_leaves_an_unoffered_recovery_alone(qtbot) -> None:
    first = MainWindow()
    qtbot.addWidget(first)
    _rename(first, "Untitled work")
    first.autosave()
    first._autosave_timer.stop()
    first.ask = lambda title, text: True  # the window is closed with its work
    kept = recovery.recovery_file(None)
    other = MainWindow()  # a new, clean window; the timer fires
    qtbot.addWidget(other)
    other.autosave()
    assert kept.exists()


def test_work_discarded_on_purpose_does_not_come_back(window) -> None:
    kept = _file(window)
    _rename(window, "Changed")
    window.autosave()
    assert kept.exists()
    window.new_project()  # asks "Discard the unsaved changes?" and is told yes
    assert not kept.exists()


def test_work_kept_on_a_no_stays_recoverable(window) -> None:
    kept = _file(window)
    _rename(window, "Changed")
    window.autosave()
    window.ask = lambda title, question: False
    window.new_project()  # the user decides not to discard
    assert kept.exists()
    assert window.document.figure.name == "Changed"
    # The window is closed with the test; refusing again would keep it open, on
    # screen, for the tests that follow.
    window.ask = lambda title, question: True


def test_the_untitled_folder_is_asked_when_needed(monkeypatch) -> None:
    """Not when the module is imported, before the application has its name."""
    monkeypatch.setattr(recovery, "UNTITLED_FOLDER", None)
    assert recovery.untitled_folder().name == "recovery"


def test_a_project_saved_as_another_leaves_no_recovery_of_the_first(
    window, tmp_path: Path
) -> None:
    first = window.document.path
    _rename(window, "Changed")
    window.autosave()
    assert recovery.recovery_file(first).exists()
    window._save_to(tmp_path / "copy.figscribe")  # what Save As does
    assert not recovery.recovery_file(first).exists()
    assert not recovery.recovery_file(window.document.path).exists()
