"""The everyday actions of U5, the way a person uses them: duplicate with
Ctrl+D, copy and paste a style, give panels one range, copy the figure to the
clipboard, show a data file in the file manager."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import QApplication

from figscribe.commands import InsertItem, add_panel
from figscribe.gui import MainWindow, clipboard, reveal
from figscribe.gui.app import create_window
from figscribe.model import ErrorbarPlot, LinePlot


@pytest.fixture
def window(qtbot, example: Path, monkeypatch) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True  # close without saving
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    win.revealed = []
    monkeypatch.setattr(reveal, "show_in_file_manager", win.revealed.append)
    win.resize(1200, 800)
    win.show()
    qtbot.waitExposed(win)
    return win


def _plots(window: MainWindow):
    return [a for axes in window.document.figure.axes for a in axes.artists]


def _add_line(window: MainWindow, **style) -> LinePlot:
    """A line plot in the first panel; the one in the model, not the one made."""
    document = window.document
    panel = document.figure.axes[0]
    bars = panel.artists[0]
    line = LinePlot(x=bars.x, y=bars.y, **style)
    document.push(InsertItem(panel.id, "artists", line))
    return panel.artists[-1]


def _entry(menu, text: str):
    return next(a for a in menu.actions() if a.text() == text)


def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


# --- duplicate ----------------------------------------------------------------


def test_duplicate_has_the_shortcut_ctrl_d(window: MainWindow) -> None:
    assert window.duplicate_action.shortcut() == QKeySequence("Ctrl+D")


def test_duplicating_a_plot_selects_the_copy(window: MainWindow) -> None:
    document = window.document
    bars = document.figure.axes[0].artists[0]
    document.select(bars.id)
    window.duplicate_action.trigger()
    plots = _plots(window)
    assert [type(p) for p in plots] == [ErrorbarPlot, ErrorbarPlot]
    assert document.selected == plots[1].id != bars.id
    assert document.history.undo_text == "Duplicate errorbar plot"
    document.undo()
    assert len(_plots(window)) == 1


def test_duplicating_several_plots_is_one_step(window: MainWindow) -> None:
    document = window.document
    line = _add_line(window)
    bars = document.figure.axes[0].artists[0]
    document.select_many([bars.id, line.id])
    steps = len(document.history._undo)
    window.duplicate_action.trigger()
    assert len(_plots(window)) == 4
    assert len(document.history._undo) == steps + 1
    assert len(document.selection) == 2  # the copies are chosen
    assert set(document.selection).isdisjoint({bars.id, line.id})


def test_duplicating_a_panel_puts_the_copy_beside_it(window: MainWindow) -> None:
    document = window.document
    panel = document.figure.axes[0]
    document.select(panel.id)
    window.duplicate_action.trigger()
    axes = document.figure.axes
    assert len(axes) == 2
    assert (axes[1].row, axes[1].col) == (0, 1)
    assert document.selected == axes[1].id
    assert len(axes[1].artists) == 1
    assert not window.errors


def test_duplicating_the_figure_from_the_same_action(window: MainWindow) -> None:
    document = window.document
    document.select(document.figure.id)
    window.duplicate_action.trigger()
    assert [f.name for f in document.project.figures] == ["Scan", "Scan (copy)"]
    assert document.figure.name == "Scan (copy)"


def test_nothing_to_duplicate_for_data_files_axes_or_no_selection(
    window: MainWindow,
) -> None:
    document = window.document
    document.select(None)
    assert not window.duplicate_action.isEnabled()
    document.select(document.project.sources[0].id)
    assert not window.duplicate_action.isEnabled()
    document.select(f"{document.figure.axes[0].id}/x")
    assert not window.duplicate_action.isEnabled()
    document.select(document.figure.axes[0].artists[0].id)
    assert window.duplicate_action.isEnabled()


# --- copy and paste a style ---------------------------------------------------


def test_paste_waits_for_a_copied_style(window: MainWindow) -> None:
    document = window.document
    line = _add_line(window)
    document.select(line.id)
    assert not window.paste_style_action.isEnabled()
    assert window.copy_style_action.isEnabled()
    window.copy_style_action.trigger()
    assert window.paste_style_action.isEnabled()


def test_a_style_is_copied_from_one_plot_and_pasted_onto_another(
    window: MainWindow,
) -> None:
    document = window.document
    line = _add_line(window, color="tab:red", linestyle="--")
    bars = document.figure.axes[0].artists[0]
    document.select(line.id)
    window.copy_style_action.trigger()
    document.select(bars.id)
    window.paste_style_action.trigger()
    assert bars.color == "tab:red" and bars.linestyle == "--"
    assert document.history.undo_text == "Paste style"
    document.undo()
    assert bars.color != "tab:red"


def test_the_copied_style_is_the_one_copied_not_the_later_one(
    window: MainWindow,
) -> None:
    document = window.document
    line = _add_line(window, color="tab:red")
    bars = document.figure.axes[0].artists[0]
    document.select(line.id)
    window.copy_style_action.trigger()
    line.color = "tab:green"  # changed afterwards
    document.select(bars.id)
    window.paste_style_action.trigger()
    assert bars.color == "tab:red"


def test_a_style_goes_to_all_chosen_plots(window: MainWindow) -> None:
    document = window.document
    source = _add_line(window, color="tab:purple")
    first, second = _add_line(window), _add_line(window)
    document.select(source.id)
    window.copy_style_action.trigger()
    document.select_many([first.id, second.id])
    window.paste_style_action.trigger()
    assert (first.color, second.color) == ("tab:purple", "tab:purple")
    assert document.history.undo_text == "Paste style to 2 plots"


def test_pasting_the_look_a_plot_has_says_so(window: MainWindow) -> None:
    document = window.document
    line = _add_line(window)
    document.select(line.id)
    window.copy_style_action.trigger()
    steps = len(document.history._undo)
    window.paste_style_action.trigger()
    assert len(document.history._undo) == steps  # no step that does nothing
    assert "already" in window.statusBar().currentMessage()


def test_copy_style_needs_a_plot(window: MainWindow) -> None:
    document = window.document
    document.select(document.figure.axes[0].id)
    assert not window.copy_style_action.isEnabled()


# --- the same range in all panels ---------------------------------------------


@pytest.fixture
def two_panels(window: MainWindow) -> MainWindow:
    document = window.document
    command, second = add_panel(document.project, document.figure.axes[0].id, "below")
    document.push(command)
    bars = document.figure.axes[0].artists[0]
    document.push(
        InsertItem(second.id, "artists", LinePlot(x=bars.x, y=bars.yerr)),
    )
    window.preview.grab()
    return window


def test_the_panel_menu_offers_the_same_range(two_panels: MainWindow) -> None:
    window = two_panels
    first = window.document.figure.axes[0]
    menu = window.outline.context_menu(first.id)
    assert "Same x range in all panels" in _texts(menu)
    assert "Same y range in all panels" in _texts(menu)


def test_the_range_a_panel_shows_goes_to_the_others(two_panels: MainWindow) -> None:
    window = two_panels
    document = window.document
    first, second = document.figure.axes
    shown = window.preview.axis_limits(f"{first.id}/x")
    _entry(
        window.outline.context_menu(first.id), "Same x range in all panels"
    ).trigger()
    assert first.x.limits == pytest.approx(shown)
    assert second.x.limits == pytest.approx(shown)
    assert first.y.limits is None and second.y.limits is None
    assert document.history.undo_text == "Same x range in all panels"
    document.undo()
    assert second.x.limits is None


def test_a_right_click_on_a_panel_offers_it_too(two_panels: MainWindow) -> None:
    window = two_panels
    document = window.document
    first, second = document.figure.axes
    preview = window.preview
    ax = next(a for a in preview._figure.axes if a.get_gid() == first.id)
    x, y = ax.transAxes.transform((0.05, 0.95))  # a corner, away from the data
    menu = preview.context_menu(preview._to_widget(x, y))
    assert "Same y range in all panels" in _texts(menu)
    _entry(menu, "Same y range in all panels").trigger()
    assert first.y.limits == pytest.approx(second.y.limits)
    assert first.y.limits is not None


def test_a_zoomed_panel_shows_the_new_range(two_panels: MainWindow) -> None:
    window = two_panels
    first, second = window.document.figure.axes
    window.preview.view[second.id] = ((0.0, 1.0), (0.0, 1.0))  # zoomed, not adopted
    window.preview.refresh()
    _entry(
        window.outline.context_menu(first.id), "Same x range in all panels"
    ).trigger()
    assert second.id not in window.preview.view
    ax = next(a for a in window.preview._figure.axes if a.get_gid() == second.id)
    assert ax.get_xlim() == pytest.approx(first.x.limits)


def test_a_turned_axis_stays_turned(two_panels: MainWindow) -> None:
    window = two_panels
    document = window.document
    first, second = document.figure.axes
    first.y.limits = (3.0, -1.0)
    document.push(  # one more step, so the model is rendered again
        InsertItem(
            first.id, "artists", LinePlot(x=first.artists[0].x, y=first.artists[0].y)
        )
    )
    _entry(
        window.outline.context_menu(first.id), "Same y range in all panels"
    ).trigger()
    assert second.y.limits == (3.0, -1.0)


def test_one_panel_has_no_others_to_give_a_range_to(window: MainWindow) -> None:
    menu = window.outline.context_menu(window.document.figure.axes[0].id)
    entry = _entry(menu, "Same x range in all panels")
    assert not entry.isEnabled()


def test_a_panel_left_out_is_named(two_panels: MainWindow) -> None:
    window = two_panels
    first, second = window.document.figure.axes
    second.x.unit = "h"
    first.x.unit = "s"
    window.document.push(
        InsertItem(
            second.id, "artists", LinePlot(x=first.artists[0].x, y=first.artists[0].y)
        )
    )
    _entry(
        window.outline.context_menu(first.id), "Same x range in all panels"
    ).trigger()
    assert second.x.limits is None
    assert "Left out" in window.statusBar().currentMessage()


# --- copy the figure ----------------------------------------------------------


def test_the_figure_is_copied_as_png_and_svg(window: MainWindow) -> None:
    QApplication.clipboard().clear()
    window.copy_figure_action.trigger()
    mime = QApplication.clipboard().mimeData()
    assert "image/png" in mime.formats() and "image/svg+xml" in mime.formats()
    assert bytes(mime.data("image/png")).startswith(b"\x89PNG\r\n\x1a\n")
    assert b"<svg" in bytes(mime.data("image/svg+xml"))
    image = QGuiApplication.clipboard().image()
    assert not image.isNull()
    assert "clipboard" in window.statusBar().currentMessage()
    assert not window.errors


def test_the_copy_is_the_figure_as_exported(window: MainWindow, tmp_path: Path) -> None:
    window.copy_figure_action.trigger()
    mime = QApplication.clipboard().mimeData()
    window.export_to(tmp_path / "f.png")
    assert bytes(mime.data("image/png")) == (tmp_path / "f.png").read_bytes()


def test_at_the_end_the_clipboard_keeps_the_bitmap(window: MainWindow) -> None:
    """Qt deletes the clipboard's contents after Python has shut down; a figure
    put there from Python would crash that, so it is handed over."""
    window.copy_figure_action.trigger()
    clipboard.release()
    mime = QApplication.clipboard().mimeData()
    assert "image/svg+xml" not in mime.formats()
    assert not QApplication.clipboard().image().isNull()


# --- show the data file -------------------------------------------------------


def test_a_data_file_can_be_shown_in_the_file_manager(window: MainWindow) -> None:
    source = window.document.project.sources[0]
    menu = window.outline.context_menu(source.id)
    _entry(menu, reveal.reveal_label()).trigger()
    (shown,) = window.revealed
    assert shown.resolve() == (window.document.base_dir / "scan.csv").resolve()
    assert not window.errors


def test_a_missing_data_file_says_where_to_look(window: MainWindow) -> None:
    source = window.document.project.sources[0]
    (window.document.base_dir / "scan.csv").unlink()
    _entry(window.outline.context_menu(source.id), reveal.reveal_label()).trigger()
    assert window.revealed == []
    title, text = window.errors[0]
    assert title == "Cannot show the file"
    assert "scan.csv" in text and "Locate file" in text
