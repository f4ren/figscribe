"""*Export Figure…* and *Export All Figures…* remember the last format and
folder (E4), and suggest the figure's name as the file name."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from figscribe.gui import MainWindow
from figscribe.gui.document import Document


class Asked:
    """What the dialogs were given, and what the user answers."""

    def __init__(self) -> None:
        self.save: list[tuple] = []
        self.answer: tuple[str, str] = ("", "")
        self.folder = ""
        self.format = ""
        self.item_asked: list[tuple] = []
        self.directories: list[str] = []


@pytest.fixture
def asked(monkeypatch) -> Asked:
    seen = Asked()

    def save(parent, caption, directory, filter_, selected=""):
        seen.save.append((caption, directory, filter_, selected))
        return seen.answer

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save)

    def directory(parent, caption, start="", *args, **kwargs):
        seen.directories.append(start)
        return seen.folder

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", directory)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )

    def item(parent, title, label, items, current=0, *args, **kwargs):
        seen.item_asked.append((list(items), current))
        return (seen.format or items[current], True)

    monkeypatch.setattr(QInputDialog, "getItem", item)
    return seen


def _window(qtbot, example: Path, settings: QSettings | None) -> MainWindow:
    win = MainWindow(Document.open(example), settings=settings)
    qtbot.addWidget(win)
    return win


@pytest.fixture
def ini(tmp_path: Path) -> str:
    return str(tmp_path / "settings.ini")


def _settings(ini: str) -> QSettings:
    return QSettings(ini, QSettings.Format.IniFormat)


def test_the_first_export_offers_pdf_next_to_the_project_named_after_the_figure(
    qtbot, example: Path, asked: Asked
) -> None:
    win = _window(qtbot, example, None)
    asked.answer = ("", "")  # cancelled
    win._export_dialog()
    _, directory, _, selected = asked.save[0]
    name = Path(directory)
    assert name.parent == example.parent
    assert name.suffix == ".pdf"
    assert name.stem  # the figure's name, made safe
    assert selected.startswith("PDF")


def test_the_format_and_folder_chosen_are_offered_next_time(
    qtbot, example: Path, asked: Asked, tmp_path: Path
) -> None:
    win = _window(qtbot, example, None)
    elsewhere = tmp_path / "out"
    elsewhere.mkdir()
    asked.answer = (str(elsewhere / "fig.png"), "PNG (*.png)")
    win._export_dialog()
    assert (elsewhere / "fig.png").is_file()

    asked.answer = ("", "")
    win._export_dialog()
    _, directory, _, selected = asked.save[-1]
    assert Path(directory).parent == elsewhere
    assert Path(directory).suffix == ".png"
    assert selected.startswith("PNG")


def test_it_is_kept_between_two_windows(
    qtbot, example: Path, asked: Asked, tmp_path: Path, ini: str
) -> None:
    elsewhere = tmp_path / "out"
    elsewhere.mkdir()
    first = _window(qtbot, example, _settings(ini))
    asked.answer = (str(elsewhere / "fig.svg"), "SVG (*.svg)")
    first._export_dialog()

    second = _window(qtbot, example, _settings(ini))
    asked.answer = ("", "")
    second._export_dialog()
    _, directory, _, selected = asked.save[-1]
    assert Path(directory).parent == elsewhere and Path(directory).suffix == ".svg"
    assert selected.startswith("SVG")


def test_a_name_typed_without_a_suffix_gets_the_one_of_the_chosen_format(
    qtbot, example: Path, asked: Asked, tmp_path: Path
) -> None:
    win = _window(qtbot, example, None)
    asked.answer = (str(tmp_path / "plain"), "SVG (*.svg)")
    win._export_dialog()
    assert (tmp_path / "plain.svg").is_file()


def test_a_suffix_typed_decides_the_format_to_remember(
    qtbot, example: Path, asked: Asked, tmp_path: Path
) -> None:
    win = _window(qtbot, example, None)
    asked.answer = (str(tmp_path / "typed.png"), "PDF (*.pdf)")  # the filter lags
    win._export_dialog()
    assert (tmp_path / "typed.png").is_file()
    asked.answer = ("", "")
    win._export_dialog()
    assert asked.save[-1][3].startswith("PNG")


def test_a_folder_that_has_gone_falls_back_to_the_projects(
    qtbot, example: Path, asked: Asked, tmp_path: Path, ini: str
) -> None:
    gone = tmp_path / "gone"
    gone.mkdir()
    win = _window(qtbot, example, _settings(ini))
    asked.answer = (str(gone / "fig.pdf"), "PDF (*.pdf)")
    win._export_dialog()
    for child in gone.iterdir():
        child.unlink()
    gone.rmdir()
    asked.answer = ("", "")
    win._export_dialog()
    assert Path(asked.save[-1][1]).parent == example.parent


def test_export_all_offers_the_last_format_and_folder(
    qtbot, example: Path, asked: Asked, tmp_path: Path, ini: str
) -> None:
    elsewhere = tmp_path / "all"
    elsewhere.mkdir()
    win = _window(qtbot, example, _settings(ini))
    asked.folder, asked.format = str(elsewhere), "PNG"
    win._export_all_dialog()
    assert list(elsewhere.glob("*.png"))

    again = _window(qtbot, example, _settings(ini))
    again._export_all_dialog()
    assert Path(asked.directories[-1]) == elsewhere
    items, current = asked.item_asked[-1]
    assert items[current] == "PNG"


# --- TIFF, EPS and a transparent background (R3, decision 0065) -------------------


def test_tiff_and_eps_are_offered_and_written(
    qtbot, example: Path, asked: Asked, tmp_path: Path
) -> None:
    win = _window(qtbot, example, None)
    asked.answer = ("", "")
    win._export_dialog()
    filters = asked.save[-1][2]
    assert "TIFF (*.tif)" in filters and "EPS (*.eps)" in filters
    for name, chosen in (("fig.tif", "TIFF (*.tif)"), ("fig.eps", "EPS (*.eps)")):
        asked.answer = (str(tmp_path / name), chosen)
        win._export_dialog()
        assert (tmp_path / name).stat().st_size > 0


def test_a_typed_tiff_suffix_is_taken_as_it_is(
    qtbot, example: Path, asked: Asked, tmp_path: Path
) -> None:
    win = _window(qtbot, example, None)
    asked.answer = (str(tmp_path / "fig.tiff"), "PDF (*.pdf)")
    win._export_dialog()
    assert (tmp_path / "fig.tiff").is_file()
    assert not (tmp_path / "fig.tiff.pdf").exists()
    assert win._text_setting("export/format") == "TIFF"


def test_the_transparent_background_is_a_switch_that_is_kept(
    qtbot, example: Path, asked: Asked, tmp_path: Path, ini: str
) -> None:
    from PIL import Image

    first = _window(qtbot, example, _settings(ini))
    assert not first.transparent_action.isChecked()
    asked.answer = (str(tmp_path / "solid.png"), "PNG (*.png)")
    first._export_dialog()
    first.transparent_action.trigger()
    asked.answer = (str(tmp_path / "clear.png"), "PNG (*.png)")
    first._export_dialog()
    assert Image.open(tmp_path / "solid.png").convert("RGBA").getpixel((1, 1))[3] == 255
    assert Image.open(tmp_path / "clear.png").convert("RGBA").getpixel((1, 1))[3] == 0

    second = _window(qtbot, example, _settings(ini))
    assert second.transparent_action.isChecked()  # kept between runs
    folder = tmp_path / "all"
    folder.mkdir()
    second.export_all(folder, ".png")
    (made,) = folder.glob("*.png")
    assert Image.open(made).convert("RGBA").getpixel((1, 1))[3] == 0
