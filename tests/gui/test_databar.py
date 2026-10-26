"""The bar above the preview for data files that changed or moved."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import QLabel, QPushButton

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.io import sha256_of

ROWS = "\n".join(f"{t:.2f},{t / 10:.3f},0.040" for t in range(12))
LONGER = f"# Synthetic Gaussian scan\nt,U,dU\ns,V,V\n{ROWS}\n"
WITHOUT_DU = "# Synthetic Gaussian scan\nt,U\ns,V\n0.00,0.1\n0.25,0.2\n"


def _open(qtbot, project: Path) -> MainWindow:
    win = create_window([str(project)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.show_error = lambda title, exc: None
    win.show()
    qtbot.waitExposed(win)
    return win


def _texts(window: MainWindow) -> str:
    """What the bar shows; labels it holds but hides do not count."""
    bar = window.data_bar
    return " ".join(
        label.text() for label in bar.findChildren(QLabel) if label.isVisibleTo(bar)
    )


def _click(window: MainWindow, text: str, row: int = 0) -> None:
    bar = window.data_bar
    buttons = [
        b
        for b in bar.findChildren(QPushButton)
        if b.text() == text and b.isVisibleTo(bar)
    ]
    buttons[row].click()


def test_no_bar_while_the_data_is_as_imported(qtbot, example: Path) -> None:
    window = _open(qtbot, example)
    assert window.data_bar.isHidden()


def test_a_changed_file_can_be_taken_as_it_is_now(qtbot, example: Path) -> None:
    (example.parent / "scan.csv").write_text(LONGER, encoding="utf-8")
    window = _open(qtbot, example)
    assert not window.data_bar.isHidden()
    assert "scan.csv has changed" in _texts(window)
    window.data_bar.rebuild()  # as when the window comes to the front again
    assert "scan.csv has changed" in _texts(window)
    assert window.preview.error is not None

    messages = []
    window.data_bar.show_message = lambda title, text: messages.append(text)
    _click(window, "Show what changed")
    assert "unknown → 12 rows" in messages[0]  # imported before rows were recorded

    _click(window, "Use the new version")
    source = window.document.project.sources[0]
    assert source.sha256 == sha256_of(example.parent / "scan.csv")
    assert window.data_bar.isHidden() and window.preview.error is None
    assert window.document.history.undo_text == "Use the new version of scan.csv"

    window.document.undo()
    assert not window.data_bar.isHidden()


def test_a_missing_file_can_be_located(qtbot, example: Path) -> None:
    moved = example.parent / "raw" / "scan.csv"
    moved.parent.mkdir()
    (example.parent / "scan.csv").rename(moved)
    window = _open(qtbot, example)
    assert "scan.csv is missing" in _texts(window)

    window.data_bar.choose_file = lambda source: moved
    _click(window, "Locate file…")
    assert window.document.project.sources[0].path == "raw/scan.csv"
    assert window.data_bar.isHidden() and window.preview.error is None


def test_columns_the_new_version_lacks_are_listed(qtbot, example: Path) -> None:
    (example.parent / "scan.csv").write_text(WITHOUT_DU, encoding="utf-8")
    window = _open(qtbot, example)
    _click(window, "Use the new version")
    assert not window.data_bar.isHidden()
    assert "measurement" in _texts(window) and "dU" in _texts(window)
    problems = [window.problems.item(i).text() for i in range(window.problems.count())]
    assert any("'dU'" in problem for problem in problems)


def test_several_files_share_one_bar(qtbot, example: Path) -> None:
    from figscribe.io import csv_source
    from figscribe.model import dumps, loads

    shutil.copy(example.parent / "scan.csv", example.parent / "second.csv")
    project = loads(example.read_text(encoding="utf-8"))
    project.sources.append(
        csv_source(
            example.parent / "second.csv", example.parent, header_row=1, skip_rows=1
        )
    )
    example.write_text(dumps(project), encoding="utf-8")
    for name in ("scan.csv", "second.csv"):
        (example.parent / name).write_text(LONGER, encoding="utf-8")

    window = _open(qtbot, example)
    text = _texts(window)
    assert "scan.csv has changed" in text and "second.csv has changed" in text
    _click(window, "Use the new version", row=1)
    assert "second.csv" not in _texts(window)
    assert "scan.csv has changed" in _texts(window)
