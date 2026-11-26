"""Breaking an axis in the GUI: the rows in the axis form, the preview's menu,
and the problem list. The data are points from 0 to 20 and one far at 419.5,
as a measurement at the zinc point."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from figscribe.commands import SetField
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.axisform import axis_settings
from figscribe.gui.document import axis_id
from figscribe.gui.palette import matching
from figscribe.io.csvfile import csv_source
from figscribe.model import (
    Axes,
    AxisSpec,
    ColumnRef,
    Figure,
    GridLayout,
    LinePlot,
    Project,
    dumps,
    validate_references,
)
from figscribe.render.breaks import widest_gap


def _project(folder: Path, panels: int = 1) -> Path:
    t = np.r_[np.linspace(0.0, 20.0, 11), 419.5]
    u = np.r_[1 + 0.1 * np.linspace(0.0, 20.0, 11), 9.0]
    rows = "\n".join(f"{a:.2f},{b:.3f}" for a, b in zip(t, u, strict=True))
    (folder / "far.csv").write_text(f"t,U\n{rows}\n", encoding="utf-8")
    source = csv_source(folder / "far.csv", folder)
    ref = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    figure = Figure(
        layout=GridLayout(rows=panels, share_x="col" if panels > 1 else "none"),
        axes=[
            Axes(row=i, artists=[LinePlot(x=ref["t"], y=ref["U"])])
            for i in range(panels)
        ],
    )
    project = Project(
        created=datetime(2026, 11, 26, tzinfo=UTC),
        sources=[source],
        figures=[figure],
    )
    path = folder / "far.figscribe"
    path.write_text(dumps(project), encoding="utf-8")
    return path


def _open(qtbot, folder: Path, panels: int = 1) -> MainWindow:
    win = create_window([str(_project(folder, panels))])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.resize(1300, 900)
    win.show()
    qtbot.waitExposed(win)
    return win


@pytest.fixture
def window(qtbot, tmp_path) -> MainWindow:
    return _open(qtbot, tmp_path)


def _axes(window, i: int = 0):
    return window.document.figure.axes[i]


def _form(window, field: str = "x", i: int = 0):
    window.document.select(axis_id(_axes(window, i).id, field))
    return window.properties.axis_form


def _enter(edit, text: str) -> None:
    edit.setText(text)
    edit.editingFinished.emit()


def test_the_widest_empty_stretch_is_proposed() -> None:
    values = np.r_[np.linspace(0.0, 20.0, 11), 419.5]
    assert widest_gap(values, []) == (21.0, 418.0)


def test_no_stretch_is_proposed_where_there_is_none() -> None:
    assert widest_gap(np.array([3.0, 3.0]), []) is None
    assert widest_gap(np.array([]), []) is None


def test_add_a_break_cuts_the_widest_gap_in_one_step(window) -> None:
    form = _form(window)
    assert form.break_rows == []
    form.add_break.click()
    assert _axes(window).x.breaks == [(21.0, 418.0)]
    (row,) = form.break_rows
    assert (row.start.text(), row.end.text()) == ("21", "418")
    assert window.preview._figure.axes[0].get_xscale() == "function"
    window.document.undo()
    assert _axes(window).x.breaks == [] and form.break_rows == []


def test_the_ends_are_typed_and_a_break_removed(window) -> None:
    form = _form(window)
    form.add_break.click()
    _enter(form.break_rows[0].start, "30")
    assert _axes(window).x.breaks == [(30.0, 418.0)]
    form.add_break.click()  # no other empty stretch: an empty row to type in
    assert _axes(window).x.breaks == [(30.0, 418.0)]
    new = form.break_rows[1]
    assert (new.start.text(), new.end.text()) == ("", "")
    _enter(new.start, "5")
    assert _axes(window).x.breaks == [(30.0, 418.0)]  # only half a break yet
    _enter(new.end, "8")
    assert _axes(window).x.breaks == [(5.0, 8.0), (30.0, 418.0)]  # in order
    form.break_rows[0].remove.click()
    assert _axes(window).x.breaks == [(30.0, 418.0)]


def test_the_empty_row_goes_again(window) -> None:
    form = _form(window)
    form.add_break.click()
    form.add_break.click()
    assert len(form.break_rows) == 2
    form.break_rows[1].remove.click()
    assert len(form.break_rows) == 1 and _axes(window).x.breaks == [(21.0, 418.0)]


def test_a_break_the_wrong_way_round_is_said_and_not_taken(window) -> None:
    form = _form(window)
    form.add_break.click()
    _enter(form.break_rows[0].start, "500")
    assert _axes(window).x.breaks == [(21.0, 418.0)]
    assert "start below its end" in window.properties._error.text()


def test_the_ends_are_in_the_shown_unit(window) -> None:
    window.document.push(SetField(_axes(window).id, ("x", "prefix"), "k"))
    window.document.push(SetField(_axes(window).id, ("x", "breaks"), [(21, 418)]))
    form = _form(window)
    assert form.break_rows[0].start.text() == "0.021"
    _enter(form.break_rows[0].end, "0.4")
    assert _axes(window).x.breaks == [(21.0, 400.0)]


def test_panels_sharing_the_axis_are_broken_together(qtbot, tmp_path) -> None:
    window = _open(qtbot, tmp_path, panels=2)
    _form(window, i=1).add_break.click()
    assert [a.x.breaks for a in window.document.figure.axes] == [[(21.0, 418.0)]] * 2
    window.document.undo()
    assert [a.x.breaks for a in window.document.figure.axes] == [[], []]


def test_a_log_axis_greys_the_breaks_and_says_why(window) -> None:
    window.document.push(SetField(_axes(window).id, ("y", "scale"), "log"))
    form = _form(window, "y")
    assert not form.add_break.isEnabled()
    assert "linear" in form.add_break.toolTip()


def test_a_broken_axis_is_not_made_logarithmic(window) -> None:
    form = _form(window)
    form.add_break.click()
    form.scale.setCurrentIndex(form.scale.findData("log"))
    form.scale.activated.emit(form.scale.currentIndex())
    assert _axes(window).x.scale == "linear"
    assert "Remove the breaks first" in window.properties._error.text()


def test_the_right_axis_has_no_breaks(window) -> None:
    window.document.push(SetField(_axes(window).id, ("y_right",), AxisSpec()))
    form = _form(window, "y_right")
    assert form.breaks_holder.isHidden()
    assert ("Scale", "Breaks") not in axis_settings(AxisSpec(), "y_right")


def test_the_search_finds_breaks_by_what_people_call_them(window) -> None:
    window.document.select(_axes(window).id)
    entries = window.palette_entries()
    for word in ("break", "broken axis", "gap", "interrupt", "skip"):
        assert any(e.text == "Breaks" for e in matching(entries, word)), word


def _menu_at(window, xdata: float, ydata: float):
    preview = window.preview
    ax = preview._figure.axes[0]
    x, y = ax.transData.transform((xdata, ydata))
    return preview.context_menu(preview._to_widget(x, y))


def _entry(menu, start: str):
    return next(a for a in menu.actions() if a.text().startswith(start))


def test_right_click_in_the_empty_stretch_breaks_the_axis_there(window) -> None:
    action = _entry(_menu_at(window, 200.0, 5.0), "Break the x axis")
    assert action.text() == "Break the x axis (cut out 21 to 418)"
    action.trigger()
    assert _axes(window).x.breaks == [(21.0, 418.0)]
    menu = _menu_at(window, 10.0, 5.0)
    assert not [a for a in menu.actions() if a.text().startswith("Break the x axis")]
    _entry(menu, "Remove the breaks of the x axis").trigger()
    assert _axes(window).x.breaks == []


def test_data_without_a_gap_offer_no_break(qtbot, example: Path) -> None:
    window = create_window([str(example)])
    qtbot.addWidget(window)
    window.ask = lambda title, question: True
    window.resize(1300, 900)
    window.show()
    qtbot.waitExposed(window)
    preview = window.preview
    ax = preview._figure.axes[0]
    x, y = ax.transAxes.transform((0.5, 0.5))
    menu = preview.context_menu(preview._to_widget(x, y))
    assert not [a for a in menu.actions() if a.text().startswith("Break the")]


def test_zooming_a_broken_axis_draws_it_anew(window) -> None:
    """The fast redraw would keep the ticks where they were."""
    _form(window).add_break.click()
    assert not window.preview._ticks_hold(window.document.figure)


def test_the_problem_list_counts_the_points_in_a_break(window, tmp_path) -> None:
    window.document.push(SetField(_axes(window).id, ("x", "breaks"), [(5.0, 11.0)]))
    document = window.document
    messages = [str(i) for i in validate_references(document.project, document.data)]
    assert any("3 points lie in a break and are not shown" in m for m in messages)


def test_a_broken_axis_says_so_in_the_panel_summary(window) -> None:
    _form(window).add_break.click()
    window.document.select(_axes(window).id)
    texts = [b.text() for b in window.properties.axis_links.values()]
    assert any("broken at 21 – 418" in t for t in texts), texts
