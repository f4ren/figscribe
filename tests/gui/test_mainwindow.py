"""The main window: files, undo/redo, deleting, outline and problems."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QKeySequence

from figscribe.commands import SetField
from figscribe.gui import Document, MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.outline import ID_ROLE


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    # No modal dialogs in tests: they would block, also when qtbot closes the
    # window at teardown.
    win.ask = lambda title, question: True
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    return win


def _data_artist(window: MainWindow):
    return window.document.project.figures[0].axes[0].artists[0]


def test_opens_the_project_from_the_command_line(window: MainWindow) -> None:
    assert window.windowTitle() == "scan.figscribe — figscribe"
    assert window.preview.error is None
    assert window.problems.count() == 0


def test_the_outline_lists_figures_axes_and_artists(window: MainWindow) -> None:
    project = window.document.project
    for oid in (
        project.sources[0].id,
        project.figures[0].id,
        project.figures[0].axes[0].id,
        _data_artist(window).id,
    ):
        assert window.outline.item_for(oid) is not None
    assert "measurement" in window.outline.item_for(_data_artist(window).id).text(0)


def test_outline_and_preview_share_the_selection(window: MainWindow) -> None:
    artist = _data_artist(window)
    window.outline.setCurrentItem(window.outline.item_for(artist.id))
    assert window.document.selected == artist.id
    assert window.preview.selection_rect() is not None

    window.document.select(None)
    assert window.outline.selectedItems() == []
    window.document.select(artist.id)
    assert window.outline.currentItem().data(0, ID_ROLE) == artist.id


def test_undo_redo_actions_follow_the_history(window: MainWindow) -> None:
    assert not window.undo_action.isEnabled()
    figure = window.document.figure
    window.document.push(SetField(figure.id, ("name",), "Renamed"))

    assert window.undo_action.isEnabled()
    assert window.undo_action.text() == "&Undo Set name"
    assert window.windowTitle() == "scan.figscribe* — figscribe"
    assert "Renamed" in window.outline.item_for(figure.id).text(0)

    window.undo_action.trigger()
    assert window.document.figure.name == "Scan"
    assert window.redo_action.text() == "&Redo Set name"
    window.redo_action.trigger()
    assert window.document.figure.name == "Renamed"


def test_delete_removes_the_selection_as_one_undo_step(window: MainWindow) -> None:
    artist = _data_artist(window)
    assert not window.delete_action.isEnabled()
    window.document.select(artist.id)
    assert window.delete_action.isEnabled()

    window.delete_action.trigger()
    assert window.document.project.figures[0].axes[0].artists == []
    assert window.outline.item_for(artist.id) is None
    assert window.undo_action.text() == "&Undo Remove errorbar plot"

    window.undo_action.trigger()
    assert _data_artist(window).id == artist.id


def test_delete_removes_a_selected_axes(window: MainWindow) -> None:
    axes = window.document.project.figures[0].axes[0]
    window.document.select(axes.id)
    window.delete_action.trigger()
    assert window.document.project.figures[0].axes == []


def test_problems_appear_and_select_their_object(window: MainWindow) -> None:
    axes = window.document.project.figures[0].axes[0]
    window.document.push(SetField(axes.id, ("row",), 3))  # outside the 1x1 grid
    assert window.problems.count() == 1
    item = window.problems.item(0)
    window.problems.itemClicked.emit(item)
    assert window.document.selected == axes.id


def test_new_asks_before_discarding_changes(window: MainWindow) -> None:
    window.document.push(SetField(window.document.figure.id, ("name",), "Changed"))
    window.ask = lambda title, question: False
    window.new_project()
    assert window.document.figure.name == "Changed"

    window.ask = lambda title, question: True
    window.new_project()
    assert window.windowTitle() == "Untitled — figscribe"
    assert window.outline.item_for(window.document.figure.id) is not None


def test_closing_with_changes_can_be_cancelled(window: MainWindow) -> None:
    window.document.push(SetField(window.document.figure.id, ("name",), "Changed"))
    window.ask = lambda title, question: False
    assert not window.close()
    window.ask = lambda title, question: True
    assert window.close()


def test_a_broken_file_is_reported_and_the_project_kept(
    window: MainWindow, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.figscribe"
    broken.write_text("{not json", encoding="utf-8")
    before = window.document
    window.open_path(broken)
    assert window.document is before
    assert window.errors and "broken.figscribe" in window.errors[0][0]


def test_save_and_export(window: MainWindow, tmp_path: Path) -> None:
    window.document.push(SetField(window.document.figure.id, ("name",), "Changed"))
    assert window.save()
    assert window.windowTitle() == "scan.figscribe — figscribe"

    for suffix in (".pdf", ".svg", ".png"):
        out = tmp_path / f"figure{suffix}"
        window.export_to(out)
        assert out.stat().st_size > 0
    window.export_to(tmp_path / "figure.bmp")
    assert window.errors and "figure.bmp" in window.errors[0][0]


def test_views_follow_a_replaced_document(window: MainWindow, example: Path) -> None:
    other = Document()
    window.set_document(other)
    other.push(SetField(other.figure.id, ("name",), "Fresh"))
    assert "Fresh" in window.outline.item_for(other.figure.id).text(0)
    assert window.undo_action.isEnabled()


def test_delete_and_undo_have_their_standard_keys(window: MainWindow) -> None:
    # Pressing the keys needs an active window, which the offscreen platform
    # does not reliably give; check the binding instead.
    expected = {
        window.delete_action: QKeySequence.StandardKey.Delete,
        window.undo_action: QKeySequence.StandardKey.Undo,
        window.redo_action: QKeySequence.StandardKey.Redo,
    }
    for action, key in expected.items():
        assert action.shortcut() == QKeySequence(key)
        assert action in window.actions()


def test_export_python_script(window: MainWindow, tmp_path: Path) -> None:
    target = tmp_path / "code" / "scan_plot.py"
    target.parent.mkdir()
    window.export_script(target)
    script = target.read_text(encoding="utf-8")
    assert 'fig.savefig(HERE / "scan_plot.pdf")' in script
    assert "../" in script  # the data is found from where the script is
    assert window.script_action.shortcut().toString() == "Ctrl+Shift+E"
