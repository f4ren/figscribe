"""Files that cannot be written or have gone (B7.4): the window says so in
words, never as "a bug in figscribe". The whole window was also run once with
every menu action and outline entry on a project whose data files were
deleted and whose folder was read-only; nothing ended in a bug message."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window


@pytest.fixture
def window(qtbot, example: Path, monkeypatch) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.messages = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, text: win.messages.append(text)
    )
    return win


def _said_plainly(window: MainWindow) -> None:
    assert window.messages, "nothing was said"
    assert "bug in figscribe" not in window.messages[-1]


def test_saving_into_a_folder_that_is_not_there_is_told(
    window: MainWindow, tmp_path: Path
) -> None:
    before = window.document.path
    assert not window._save_to(tmp_path / "nodir" / "x.figscribe")
    _said_plainly(window)
    assert window.document.path == before


def test_exporting_the_figure_into_a_folder_that_is_not_there_is_told(
    window: MainWindow, tmp_path: Path
) -> None:
    window.export_to(tmp_path / "nodir" / "figure.pdf")
    _said_plainly(window)


def test_exporting_the_script_into_a_folder_that_is_not_there_is_told(
    window: MainWindow, tmp_path: Path
) -> None:
    window.export_script(tmp_path / "nodir" / "plot.py")
    _said_plainly(window)


def test_exporting_while_the_data_file_is_gone_is_told(
    qtbot, example: Path, tmp_path: Path, monkeypatch
) -> None:
    (example.parent / "scan.csv").unlink()  # the project opens without its data
    messages = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda parent, title, text: messages.append(text)
    )
    window = create_window([str(example)])
    qtbot.addWidget(window)
    window.export_to(tmp_path / "figure.pdf")
    assert messages and "bug in figscribe" not in messages[-1]
    assert "scan.csv" in messages[-1]
    assert not (tmp_path / "figure.pdf").exists()
    # Unlike `figscribe script`, which writes the script without the data, the
    # window refuses it; it says why (a follow-up under B7.4 in the roadmap).
    window.export_script(tmp_path / "plot.py")
    assert "bug in figscribe" not in messages[-1] and "scan.csv" in messages[-1]


def test_a_data_file_that_goes_while_the_figure_is_open_leaves_the_figure_as_drawn(
    window: MainWindow, example: Path, tmp_path: Path
) -> None:
    window.export_to(tmp_path / "before.pdf")  # reads the data
    (example.parent / "scan.csv").unlink()
    window.export_to(tmp_path / "after.pdf")  # what is shown is what is exported
    assert (tmp_path / "after.pdf").stat().st_size > 0
    assert not window.messages
