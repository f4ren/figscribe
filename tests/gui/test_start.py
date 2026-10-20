"""The start page and the layouts it starts from."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, QSettings

from figscribe.commands import SetField
from figscribe.examples import bundled_example
from figscribe.gui import Document, MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.start import panel_boxes
from figscribe.model import validate_references
from figscribe.render import render
from figscribe.templates import TEMPLATES, template


@pytest.mark.parametrize("key", [t.key for t in TEMPLATES])
def test_every_template_draws(key: str) -> None:
    project = Document().project
    project.figures = [template(key).build()]
    assert validate_references(project) == []
    figure = project.figures[0]
    fig = render(figure, Document(project).data)
    width, height = fig.get_size_inches()
    assert width * 25.4 == pytest.approx(figure.width_mm)
    assert height * 25.4 == pytest.approx(figure.height_mm)
    assert len(fig.axes) == len(figure.axes)


def test_templates_say_their_size() -> None:
    for candidate in TEMPLATES:
        figure = candidate.build()
        assert candidate.detail.startswith(
            f"{figure.width_mm:g} × {figure.height_mm:g} mm"
        )
    with pytest.raises(KeyError):
        template("poster")


def test_thumbnails_follow_the_grid_ratios() -> None:
    top, bottom = panel_boxes(template("residuals").build(), QRectF(0, 0, 100, 106))
    assert top.width() == bottom.width() == 100
    assert top.height() == pytest.approx(3 * bottom.height())
    left, right = panel_boxes(template("side-by-side").build(), QRectF(0, 0, 106, 50))
    assert left.right() < right.left()


def test_the_example_ships_with_figscribe() -> None:
    assert (bundled_example() / "scan.figscribe").is_file()
    assert (bundled_example() / "scan.csv").is_file()


@pytest.fixture
def window(qtbot, tmp_path: Path) -> MainWindow:
    win = create_window([])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.examples_dir = tmp_path / "examples"
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    return win


def test_starting_without_a_file_shows_the_start_page(window: MainWindow) -> None:
    assert window.on_start_page
    assert window.toolbar.isHidden()
    assert window.contents_dock.isHidden() and window.properties_dock.isHidden()
    assert window.start.back.isHidden()
    assert window.start.recent_rows == []


def test_a_layout_starts_a_new_project(window: MainWindow) -> None:
    window.start.template_tiles["residuals"].click()
    assert not window.on_start_page
    assert not window.toolbar.isHidden()
    figure = window.document.figure
    assert (figure.width_mm, figure.height_mm) == (85, 80)
    assert len(figure.axes) == 2
    assert window.document.history.is_clean


def test_a_layout_asks_before_replacing_changes(window: MainWindow) -> None:
    window.new_project()
    window.document.push(_rename(window.document, "Changed"))
    window.show_start()
    window.ask = lambda title, question: False
    window.start.template_tiles["single"].click()
    assert window.document.figure.name == "Changed"
    assert window.on_start_page


def test_the_example_is_copied_and_opened(window: MainWindow) -> None:
    window.start.example_tile.click()
    copy = window.examples_dir / "gaussian-scan" / "scan.figscribe"
    assert window.document.path == copy
    assert window.document.data is not None and window.preview.error is None

    # A second time opens the same copy, with the user's changes.
    window.document.push(_rename(window.document, "Mine"))
    window.save()
    window.show_start()
    window.start.example_tile.click()
    assert window.document.figure.name == "Mine"


def test_back_returns_to_the_open_project(window: MainWindow, example: Path) -> None:
    window.open_path(example)
    window.home_action.trigger()
    assert window.on_start_page
    assert window.start.back.text() == "Back to scan"
    window.start.back.click()
    assert not window.on_start_page
    assert window.document.path == example


def test_dropped_data_starts_a_project(window: MainWindow, example: Path) -> None:
    window.run_dialog = lambda dialog: False  # cancelled
    window.start.files_dropped.emit([example.parent / "scan.csv"])
    assert window.on_start_page

    window.run_dialog = lambda dialog: True
    window.start.files_dropped.emit([example.parent / "scan.csv"])
    assert not window.on_start_page
    assert len(window.document.project.sources) == 1
    assert len(window.document.figure.axes) == 1


def test_a_dropped_project_opens(window: MainWindow, example: Path) -> None:
    window.start.files_dropped.emit([example])
    assert window.document.path == example
    assert not window.on_start_page


def test_recent_projects_are_remembered(qtbot, tmp_path: Path, example: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.open_path(example)
    saved = tmp_path / "other.figscribe"
    win._save_to(saved)  # what "Save as" does with the chosen file
    assert win.recent == [saved.resolve(), example.resolve()]

    win.show_start()
    assert len(win.start.recent_rows) == 2
    saved.unlink()
    win.show_start()
    assert len(win.start.recent_rows) == 1  # missing files are left out
    win.new_project()
    win.show_start()
    win.start.recent_rows[0].click()
    assert win.document.path == example.resolve()


def _rename(document: Document, name: str) -> SetField:
    return SetField(document.figure.id, ("name",), name)
