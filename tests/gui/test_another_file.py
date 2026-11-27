"""Use another file, from the window."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel

from figscribe.datafile import MissingColumn
from figscribe.fit import add_fit, refit
from figscribe.gui import MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.columndialog import NOT_THERE, ColumnDialog
from figscribe.model import FitCurve, Hdf5Source, PredefinedFit, dumps


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.show()
    qtbot.waitExposed(win)
    return win


@pytest.fixture
def other(example: Path) -> Path:
    """The example's data with its peak twice as high, in a file of its own."""
    lines = (example.parent / "scan.csv").read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line[:1].isdigit():
            t, u, du = line.split(",")
            line = f"{t},{2 * float(u):.5f},{du}"
        out.append(line)
    path = example.parent / "mine.csv"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def _answer(window: MainWindow, path: Path) -> list[str]:
    messages: list[str] = []
    window.choose_data_file = lambda source: path
    window.tell = lambda title, text: messages.append(text)
    return messages


def test_the_example_is_drawn_with_ones_own_file(
    window: MainWindow, other: Path, tmp_path: Path
) -> None:
    document = window.document
    plot = document.figure.axes[0].artists[0]
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="gaussian"))
    document.push(add_fit(document.project, fit))
    document.push(refit(document.project, fit.id, document.data))
    before = dumps(document.project)
    height = document.figure.axes[0].artists[1].result.parameters["a"]

    messages = _answer(window, other)
    window.use_another_file(document.project.sources[0].id)

    source = document.project.sources[0]
    assert source.path == "mine.csv" and window.preview.error is None
    assert window.data_bar.isHidden()
    new = document.figure.axes[0].artists[1].result.parameters["a"]
    assert new == pytest.approx(2 * height, rel=0.05)
    assert messages == []  # nothing the user has to know
    assert document.history.undo_text == "Use another file for scan.csv"
    assert "mine.csv" in window.statusBar().currentMessage()

    document.undo()
    assert dumps(document.project) == before
    document.redo()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    document.save(elsewhere / "copy.figscribe")
    assert document.data_states() == {}  # found from the new folder


def test_what_has_to_be_known_is_told(window: MainWindow, example: Path) -> None:
    path = example.parent / "short.csv"
    path.write_text("# a scan\nt,U\ns,V\n0.0,0.1\n0.5,0.2\n", encoding="utf-8")
    messages = _answer(window, path)
    window.run_dialog = lambda dialog: True  # the columns, as proposed
    window.use_another_file(window.document.project.sources[0].id)
    assert "no column dU" in " ".join(messages)


def test_a_file_that_cannot_be_read_is_told(window: MainWindow, example) -> None:
    path = example.parent / "words.csv"
    path.write_text("a, scan\nt,U,dU\ns,V,V\nzero,one,two\n", encoding="utf-8")
    _answer(window, path)
    errors = []
    window.show_error = lambda title, exc: errors.append(str(exc))
    before = dumps(window.document.project)
    window.use_another_file(window.document.project.sources[0].id)
    assert errors and "words.csv" in errors[0]
    assert dumps(window.document.project) == before


def test_it_is_offered_where_the_file_is(window: MainWindow) -> None:
    source = window.document.project.sources[0]
    asked = []
    window.choose_data_file = lambda s: asked.append(s.id)  # and cancelled
    menu = window.outline.context_menu(source.id)
    action = next(a for a in menu.actions() if a.text() == "Use another file…")
    action.trigger()
    window.document.select(source.id)
    window.properties.another_file_button.click()
    entry = next(
        e for e in window.palette_entries() if e.text == "Use another file for scan.csv"
    )
    entry.run()
    assert asked == [source.id] * 3
    assert not window.document.history.can_undo


def _renamed(example: Path) -> Path:
    """The example's data, its columns under other and one under a long name."""
    text = (example.parent / "scan.csv").read_text(encoding="utf-8")
    path = example.parent / "mine.csv"
    path.write_text(text.replace("t,U,dU", f"time,signal,{LONG}"), encoding="utf-8")
    return path


LONG = "standard_uncertainty_of_the_signal_in_volts"


def test_columns_under_other_names_are_asked_for(
    window: MainWindow, example: Path
) -> None:
    """The dialog opens with the columns at the same places chosen."""
    messages = _answer(window, _renamed(example))
    seen = {}

    def run(dialog: ColumnDialog) -> bool:
        seen.update(
            {name: combo.currentText() for (_, name), combo in dialog.combos.items()}
        )
        return True

    window.run_dialog = run
    window.use_another_file(window.document.project.sources[0].id)
    assert seen == {"t": "time", "U": "signal", "dU": LONG}
    plot = window.document.figure.axes[0].artists[0]
    assert (plot.x.column, plot.y.column, plot.yerr.column) == (
        "time",
        "signal",
        LONG,
    )
    assert window.preview.error is None and window.data_bar.isHidden()
    assert messages == []


def test_a_column_can_be_picked_or_left_out(window: MainWindow, example: Path) -> None:
    messages = _answer(window, _renamed(example))

    def run(dialog: ColumnDialog) -> bool:
        combo = next(c for (_, name), c in dialog.combos.items() if name == "dU")
        _pick(combo, combo.findText(NOT_THERE))
        return True

    window.run_dialog = run
    window.use_another_file(window.document.project.sources[0].id)
    plot = window.document.figure.axes[0].artists[0]
    assert (plot.y.column, plot.yerr.column) == ("signal", "dU")
    assert "no column dU" in " ".join(messages)


def test_cancelling_the_columns_changes_nothing(
    window: MainWindow, example: Path
) -> None:
    _answer(window, _renamed(example))
    window.run_dialog = lambda dialog: False
    before = dumps(window.document.project)
    window.use_another_file(window.document.project.sources[0].id)
    assert dumps(window.document.project) == before
    assert not window.document.history.can_undo


def _pick(combo, index: int) -> None:
    """Choose an entry of the list, as a person does."""
    assert index >= 0, "no such entry"
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def _dialog(qtbot, *names: str) -> ColumnDialog:
    missing = [
        MissingColumn("s", name, ["plot <1>"], ["a", "b"], "a") for name in names
    ]
    dialog = ColumnDialog("mine.csv", missing)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog


def test_a_column_name_is_shown_as_it_is(qtbot) -> None:
    """A mean written <U> must not be taken for markup."""
    dialog = _dialog(qtbot, "<U>")
    (shown,) = [w for w in dialog.findChildren(QLabel) if w.text() == "<U>"]
    assert shown.textFormat() == Qt.TextFormat.PlainText
    assert "&lt;1&gt;" in shown.toolTip()


def test_a_long_column_name_stays_inside_the_dialog(qtbot) -> None:
    long = "a_very_long_column_name_without_any_space_" * 2 + "end"
    dialog = _dialog(qtbot, long)
    qtbot.wait(20)
    combo = dialog.combos["s", long]
    right = combo.mapTo(dialog, combo.rect().topRight()).x()
    assert right <= dialog.width()
    assert any(long in w.toolTip() for w in dialog.findChildren(QLabel))


def test_the_wheel_does_not_change_a_choice(qtbot) -> None:
    dialog = _dialog(qtbot, "t")
    combo = dialog.combos["s", "t"]
    before = combo.currentIndex()
    for delta in (-120, 120, -120):
        event = QWheelEvent(
            QPointF(5, 5),
            QPointF(combo.mapToGlobal(QPoint(5, 5))),
            QPoint(0, delta),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(combo, event)
    assert combo.currentIndex() == before


def test_another_file_is_not_offered_where_it_cannot_be_used(
    window: MainWindow,
) -> None:
    source = Hdf5Source(path="run.h5", sha256="0" * 64, dataset="/a")
    window.document.project.sources.append(source)
    window.outline.rebuild()
    menu = window.outline.context_menu(source.id)
    assert "Use another file…" not in [a.text() for a in menu.actions()]
