"""Several figures in one project: added, switched, renamed, moved,
duplicated, deleted and exported, the way a person does it."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.mainwindow import export_names
from figscribe.model import Figure


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _names(window: MainWindow) -> list[str]:
    return [f.name for f in window.document.project.figures]


def _tabs(window: MainWindow) -> list[str]:
    bar = window.figure_tabs.bar
    return [bar.tabText(i) for i in range(bar.count())]


def _menu_texts(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _drawn_panels(window: MainWindow) -> set[str]:
    return {ax.get_gid() for ax in window.preview._figure.axes}


def test_the_tabs_show_once_there_is_a_second_figure(window: MainWindow) -> None:
    assert not window.figure_tabs.isVisible()
    first = window.document.figure
    window.add_figure_action.trigger()
    added = window.document.figure
    assert _names(window) == ["Scan", "Figure 2"]
    assert window.document.selected == added.id
    assert added.width_mm == first.width_mm  # the look of the one beside it
    assert window.figure_tabs.isVisible()
    assert _tabs(window) == ["Scan", "Figure 2"]
    assert window.figure_tabs.bar.currentIndex() == 1
    assert _drawn_panels(window) == {added.axes[0].id}
    assert window.document.history.undo_text == "Add a figure"
    window.document.undo()
    assert not window.figure_tabs.isVisible()
    assert window.document.figure is window.document.project.figures[0]


def test_a_tab_or_an_object_in_a_figure_shows_it(window: MainWindow) -> None:
    window.add_figure_action.trigger()
    bar = window.figure_tabs.bar
    first = window.document.project.figures[0]
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(0).center())
    assert window.document.selected == first.id
    assert first.axes[0].id in _drawn_panels(window)
    second = window.document.project.figures[1]
    window.document.select(second.axes[0].id)  # as a click in the outline
    assert bar.currentIndex() == 1
    assert _drawn_panels(window) == {second.axes[0].id}


def test_the_code_drawer_follows_the_shown_figure(window: MainWindow) -> None:
    window.code_action.trigger()
    window.add_figure_action.trigger()
    window.code.update_now()
    assert "figure_2.pdf" in window.code.text.toPlainText()
    window.document.select(window.document.project.figures[0].id)
    window.code.update_now()
    assert "scan.pdf" in window.code.text.toPlainText()


def test_rename_by_double_click_and_move_from_the_menu(window: MainWindow) -> None:
    window.add_figure_action.trigger()
    bar = window.figure_tabs.bar
    window.ask_name = lambda title, prompt, current: f"{current}, fitted"
    QTest.mouseDClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(1).center())
    assert _names(window) == ["Scan", "Figure 2, fitted"]
    assert _tabs(window) == _names(window)
    assert window.document.history.undo_text == "Rename figure"

    menu = window.figure_tabs.figure_menu(1)
    texts = _menu_texts(menu)
    assert texts == ["Rename…", "Duplicate", "Move left", "Move right", "Delete figure"]
    assert not menu.actions()[3].isEnabled()  # the last can go no further right
    menu.actions()[2].trigger()
    assert _names(window) == ["Figure 2, fitted", "Scan"]
    assert _tabs(window) == _names(window)
    assert window.document.history.undo_text == "Move figure"


def test_a_tab_dragged_moves_its_figure_once(window: MainWindow, qtbot) -> None:
    window.add_figure_action.trigger()
    window.add_figure_action.trigger()
    bar = window.figure_tabs.bar
    steps = len(window.document.history._undo)
    bar.setCurrentIndex(0)
    bar.moveTab(0, 2)  # as dragging the first tab to the end does
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert _names(window) == ["Figure 2", "Figure 3", "Scan"]
    assert len(window.document.history._undo) == steps + 1


def test_duplicate_and_delete_from_the_outline(window: MainWindow) -> None:
    scan = window.document.figure
    menu = window.outline.context_menu(scan.id)
    texts = _menu_texts(menu)
    assert texts == ["Rename…", "Duplicate", "Move up", "Move down", "Delete figure"]
    assert not menu.actions()[-1].isEnabled()  # the only figure stays
    menu.actions()[1].trigger()
    assert _names(window) == ["Scan", "Scan (copy)"]
    copy = window.document.figure
    assert window.document.selected == copy.id
    assert window.outline.item_for(copy.id) is not None
    window.outline.context_menu(copy.id).actions()[-1].trigger()
    assert _names(window) == ["Scan"]
    assert not window.errors


def test_the_delete_key_on_the_last_figure_says_why_not(window: MainWindow) -> None:
    window.document.select(window.document.figure.id)
    window.delete_action.trigger()
    assert window.errors == [
        ("Cannot delete the figure", "a project keeps at least one figure")
    ]


def test_export_all_writes_each_figure(window: MainWindow, tmp_path: Path) -> None:
    window.add_figure_action.trigger()
    window.duplicate_figure(window.document.project.figures[0].id)
    out = tmp_path / "out"
    out.mkdir()
    written = window.export_all(out, ".pdf")
    assert [p.name for p in written] == ["scan.pdf", "scan_copy.pdf", "figure_2.pdf"]
    assert all(p.stat().st_size > 0 for p in written)
    scripts = window.export_all(out, ".py")
    assert "figure_2.pdf" in scripts[-1].read_text(encoding="utf-8")


def test_export_all_through_its_dialogs(
    window: MainWindow, tmp_path: Path, monkeypatch
) -> None:
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    window.add_figure_action.trigger()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
    )
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: ("SVG", True))
    (tmp_path / "scan.svg").write_text("old", encoding="utf-8")
    asked = []
    window.ask = lambda title, question: asked.append(question) or False
    window._export_all_dialog()
    assert "scan.svg" in asked[0]
    assert (tmp_path / "scan.svg").read_text(encoding="utf-8") == "old"
    window.ask = lambda title, question: True
    window._export_all_dialog()
    assert (tmp_path / "figure_2.svg").exists()
    assert (tmp_path / "scan.svg").read_text(encoding="utf-8") != "old"


def test_export_names_number_a_name_two_figures_share(tmp_path: Path) -> None:
    figures = [Figure(name="Scan"), Figure(name="scan"), Figure(name="Other")]
    names = [p.name for p in export_names(figures, tmp_path, ".png")]
    assert names == ["scan.png", "scan-2.png", "other.png"]
