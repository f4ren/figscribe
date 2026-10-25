"""Fitting from the GUI: the dialog, the residual panel, and fitting again."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QLabel

from figscribe.commands import InsertItem, SetField
from figscribe.fit import FitError, add_fit, refit
from figscribe.gui import Document, MainWindow
from figscribe.gui.app import create_window
from figscribe.gui.fitdialog import FitDialog
from figscribe.gui.properties import PropertyPanel
from figscribe.model import (
    Axes,
    ExpressionFit,
    FitCurve,
    GridLayout,
    PredefinedFit,
    ResidualPlot,
)


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


def _data(document: Document):
    return document.figure.axes[0].artists[0]


@pytest.fixture
def dialog(qtbot, document: Document) -> FitDialog:
    widget = FitDialog(_data(document), document.data)
    qtbot.addWidget(widget)
    return widget


def _ok(dialog: FitDialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


# --- the dialog -----------------------------------------------------------------


def test_a_gaussian_is_fitted_at_once(dialog: FitDialog) -> None:
    assert dialog.model_key == "gaussian"
    result = dialog.result
    assert result.parameters["mu"] == pytest.approx(4.967, abs=1e-3)
    assert result.uncertainties["mu"] == pytest.approx(0.023, abs=1e-3)
    assert result.reduced_chi_square == pytest.approx(0.75, abs=0.01)
    assert _ok(dialog)
    fit = dialog.fit()
    assert fit.model == PredefinedFit(name="gaussian")
    assert fit.target == dialog.target.id and fit.label == "Gaussian fit"
    assert set(fit.initial_values) == {"a", "mu", "sigma", "c"}


def test_another_model_fits_again(dialog: FitDialog) -> None:
    dialog.choose("linear")
    assert list(dialog.start) == ["a", "b"]
    assert set(dialog.result.parameters) == {"a", "b"}
    assert dialog.label.text() == "Straight line fit"

    dialog.choose("polynomial")
    dialog.degree.setValue(3)
    assert dialog.fit().model == PredefinedFit(name="polynomial", degree=3)
    assert len(dialog.result.parameters) == 4


def test_an_own_formula_finds_its_parameters(dialog: FitDialog) -> None:
    dialog.choose("expression")
    assert not _ok(dialog) and "formula" in dialog.error.text()
    dialog.expression.setText("A * exp(-(x - x0)**2 / w) + c")
    dialog.expression.editingFinished.emit()
    assert list(dialog.start) == ["A", "x0", "w", "c"]
    model = dialog.fit().model
    assert isinstance(model, ExpressionFit)
    assert model.parameters == ["A", "x0", "w", "c"]

    dialog.expression.setText("a * foo(x)")
    dialog.expression.editingFinished.emit()
    assert not _ok(dialog) and dialog.fit() is None


def test_start_values_can_be_changed(dialog: FitDialog) -> None:
    dialog.start["mu"].setText("lots")
    dialog.start["mu"].editingFinished.emit()
    assert "start value of mu" in dialog.error.text() and not _ok(dialog)
    assert "'lots'" in dialog.error.text()
    dialog.start["mu"].setText("4,5")
    dialog.start["mu"].editingFinished.emit()
    assert _ok(dialog) and dialog.fit().initial_values["mu"] == 4.5
    dialog.start["mu"].setText("0")
    dialog._guess_again()
    assert float(dialog.start["mu"].text()) != 0


def test_a_parameter_can_be_held_at_its_start_value(dialog: FitDialog) -> None:
    dialog.start["sigma"].setText("0.9")
    dialog.start["sigma"].editingFinished.emit()
    dialog.fixed["sigma"].click()
    assert dialog.result.parameters["sigma"] == 0.9
    assert dialog.result.uncertainties["sigma"] == 0.0
    fit = dialog.fit()
    assert fit.fixed == ["sigma"] and fit.initial_values["sigma"] == 0.9
    dialog.fixed["sigma"].click()
    assert dialog.result.parameters["sigma"] != 0.9


def test_a_parameter_can_be_bounded(dialog: FitDialog) -> None:
    fitted = dialog.result.parameters["a"]
    dialog.upper["a"].setText(f"{fitted * 0.9:.6g}")
    dialog.upper["a"].editingFinished.emit()
    assert dialog.result.parameters["a"] <= fitted * 0.9 * (1 + 1e-9)
    assert dialog.fit().parameter_bounds == {"a": (None, float(f"{fitted * 0.9:.6g}"))}
    dialog.lower["a"].setText(f"{fitted * 2:.6g}")  # above the upper: refused
    dialog.lower["a"].editingFinished.emit()
    assert "lower bound of a" in dialog.error.text() and not _ok(dialog)


def test_a_typed_label_is_kept(dialog: FitDialog) -> None:
    dialog.label.setText("my fit")
    dialog.label.setModified(True)
    dialog.choose("lorentzian")
    assert dialog.label.text() == "my fit"


# --- the command ----------------------------------------------------------------


def _fit(document: Document) -> FitCurve:
    return FitCurve(target=_data(document).id, model=PredefinedFit(name="linear"))


def test_a_residual_panel_is_added_below(document: Document) -> None:
    figure = document.figure
    fit = _fit(document)
    document.push(add_fit(document.project, fit, residuals=True))
    assert document.history.undo_text == "Add linear fit with residuals"
    assert figure.layout.rows == 2 and figure.layout.height_ratios == [3.0, 1.0]
    assert figure.layout.share_x == "col" and figure.height_mm == 80
    top, bottom = figure.axes
    assert top.artists[-1].id == fit.id
    assert isinstance(bottom.artists[0], ResidualPlot) and bottom.row == 1
    assert (bottom.x.label, bottom.x.unit) == ("$t$", "s")
    assert (bottom.y.label, bottom.y.unit) == ("Residual", "V")
    assert top.x.label is None and top.x.unit is None

    document.undo()
    assert len(figure.axes) == 1 and figure.height_mm == 60
    assert document.figure.axes[0].x.label == "$t$"


def test_an_empty_panel_below_is_used(document: Document) -> None:
    figure = document.figure
    document.push(SetField(figure.id, ("layout",), GridLayout(rows=2)))
    document.push(InsertItem(figure.id, "axes", Axes(row=1)))
    document.push(add_fit(document.project, _fit(document), residuals=True))
    assert len(document.figure.axes) == 2 and document.figure.height_mm == 60
    assert isinstance(document.figure.axes[1].artists[0], ResidualPlot)


def test_only_plots_with_x_and_y_are_fitted(document: Document) -> None:
    fit = _fit(document)
    document.push(add_fit(document.project, fit))
    with pytest.raises(FitError, match="cannot be fitted"):
        add_fit(document.project, FitCurve(target=fit.id, model=fit.model))
    with pytest.raises(FitError, match="no plot"):
        add_fit(document.project, FitCurve(target="gone", model=fit.model))


# --- in the window --------------------------------------------------------------


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    win.errors = []
    win.show_error = lambda title, exc: win.errors.append((title, str(exc)))
    return win


def test_fit_adds_curve_and_residuals_in_one_step(window: MainWindow) -> None:
    def accept(dialog: FitDialog) -> bool:
        dialog.residuals.setChecked(True)
        return True

    window.run_dialog = accept
    window.fit_action.trigger()  # the only plot is fitted, no selection needed
    figure = window.document.figure
    fit = figure.axes[0].artists[1]
    assert isinstance(fit, FitCurve) and fit.result is not None
    assert window.document.selected == fit.id
    assert len(figure.axes) == 2
    assert window.preview.error is None
    assert window.outline.item_for(fit.id).text(1).startswith("χ²ᵣ")
    window.document.undo()
    assert len(window.document.figure.axes[0].artists) == 1


def test_a_cancelled_fit_changes_nothing(window: MainWindow) -> None:
    window.run_dialog = lambda dialog: False
    window.add_fit()
    assert not window.document.history.can_undo


def test_without_a_plot_to_fit_the_user_is_told(window: MainWindow) -> None:
    window.new_project()
    window.add_fit()
    assert window.errors and "Select the plot" in window.errors[0][1]


def test_fitting_again_after_a_change(qtbot, document: Document) -> None:
    fit = _fit(document)
    document.push(add_fit(document.project, fit))
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    document.select(fit.id)
    panel.fit_again_button.click()
    assert document.figure.axes[0].artists[1].result is not None
    assert document.history.undo_text == "Fit linear"


def test_a_guess_moves_into_a_bound_but_a_typed_start_does_not(
    dialog: FitDialog,
) -> None:
    dialog.lower["sigma"].setText("5")
    dialog.lower["sigma"].editingFinished.emit()
    assert float(dialog.start["sigma"].text()) == 5  # the guess, moved in
    assert _ok(dialog)
    dialog.start["c"].setText("9")
    dialog.start["c"].setModified(True)  # as typed by the user
    dialog.upper["c"].setText("1")
    dialog.upper["c"].editingFinished.emit()
    assert "start value of c, 9, lies outside" in dialog.error.text()
    assert not _ok(dialog)


def test_the_panel_shows_a_held_parameter_as_held(qtbot, document: Document) -> None:
    fit = FitCurve(
        target=_data(document).id,
        model=PredefinedFit(name="gaussian"),
        initial_values={"c": 0.0},
        fixed=["c"],
    )
    document.push(add_fit(document.project, fit))
    document.push(refit(document.project, fit.id, document.data))
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    document.select(fit.id)
    shown = [w.text() for w in panel.findChildren(QLabel)]
    assert "0 (held)" in shown


# --- changing a fit that is there -------------------------------------------------


def _held_fit(document: Document) -> FitCurve:
    fit = FitCurve(
        target=_data(document).id,
        model=PredefinedFit(name="gaussian"),
        initial_values={"a": 1.0, "mu": 5.0, "sigma": 1.0, "c": 0.0},
        fixed=["c"],
        parameter_bounds={"sigma": (0.2, None)},
        label="peak",
    )
    document.push(add_fit(document.project, fit))
    document.push(refit(document.project, fit.id, document.data))
    return document.figure.axes[0].artists[1]


def test_the_dialog_shows_a_fit_as_it_is(qtbot, document: Document) -> None:
    fit = _held_fit(document)
    dialog = FitDialog(_data(document), document.data, fit=fit)
    qtbot.addWidget(dialog)
    assert dialog.model_key == "gaussian"
    assert {n: float(line.text()) for n, line in dialog.start.items()} == {
        "a": 1.0,
        "mu": 5.0,
        "sigma": 1.0,
        "c": 0.0,
    }
    assert dialog.held() == ["c"] and dialog.bounds() == {"sigma": (0.2, None)}
    assert dialog.label.text() == "peak"
    assert dialog.residuals.isHidden()
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.text() == "Update fit" and _ok(dialog)
    assert dialog.fit().id == fit.id


def test_the_panel_opens_a_fit_to_change_it(window: MainWindow) -> None:
    fit = _held_fit(window.document)
    window.document.select(fit.id)

    def free_c(dialog: FitDialog) -> bool:
        dialog.fixed["c"].click()
        return True

    window.run_dialog = free_c
    window.properties.edit_fit_button.click()
    changed = window.document.figure.axes[0].artists[1]
    assert changed.fixed == [] and changed.result.uncertainties["c"] > 0
    assert window.document.history.undo_text == "Change the fit"
    window.document.undo()
    assert window.document.figure.axes[0].artists[1].fixed == ["c"]
