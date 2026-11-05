"""Fitting an Allan deviation from the dialog (F14, decision 0064)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from figscribe.fit import add_fit, refit
from figscribe.gui import Document
from figscribe.gui.fitdialog import FitDialog
from figscribe.io import csv_source
from figscribe.model import (
    AllanDeviationPlot,
    Axes,
    AxisSpec,
    ColumnRef,
    Figure,
    FitCurve,
    PredefinedFit,
    Project,
)


@pytest.fixture
def document(tmp_path: Path) -> Document:
    rng = np.random.default_rng(3)
    y = rng.normal(scale=2e-12, size=2000)
    rows = "\n".join(f"{i * 0.5!r},{float(v)!r}" for i, v in enumerate(y))
    (tmp_path / "clock.csv").write_text(f"t,y\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "clock.csv", tmp_path, header_row=0)
    col = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    plot = AllanDeviationPlot(values=col["y"], time=col["t"])
    log = {"x": AxisSpec(scale="log"), "y": AxisSpec(scale="log")}
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(axes=[Axes(**log, artists=[plot])])],
    )
    return Document(project, tmp_path / "clock.figscribe")


def _plot(document: Document):
    return document.figure.axes[0].artists[0]


def test_the_dialog_fits_a_power_law_to_the_error_bars(qtbot, document) -> None:
    dialog = FitDialog(_plot(document), document.data)
    qtbot.addWidget(dialog)
    dialog.choose("power")
    result = dialog.result
    assert result.parameters["b"] == pytest.approx(-0.5, abs=0.1)  # white noise
    assert "weighted by the error bars" in dialog.points.text()
    fit = dialog.fit()
    assert fit.model == PredefinedFit(name="power") and fit.target == _plot(document).id


def test_no_row_can_be_left_out_of_it_and_the_dialog_says_why(qtbot, document) -> None:
    dialog = FitDialog(_plot(document), document.data)
    qtbot.addWidget(dialog)
    assert not dialog.find_outliers.isEnabled()
    assert "Allan deviation" in dialog.find_outliers.toolTip()
    assert not dialog.outside.isEnabled()
    assert "fewer points" not in dialog.outside.toolTip()


def test_the_fit_shows_in_the_panel_and_the_script(qtbot, document) -> None:
    plot = _plot(document)
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="power"))
    document.push(add_fit(document.project, fit, residuals=True))
    document.push(refit(document.project, fit.id, document.data))
    from figscribe.codegen import generate

    script = generate(
        document.project,
        document.figure,
        base_dir=document.base_dir,
        data=document.data,
    )
    assert "curve_fit(" in script and "geomspace" in script


def test_a_setting_that_changes_the_points_fits_again(qtbot, document) -> None:
    """Error bars, τ values and the rest change what is fitted: the fit follows,
    as it does for a range and for units, or the figure and the script (which
    always fits again) would differ."""
    from figscribe.gui.properties import PropertyPanel

    plot = _plot(document)
    fit = FitCurve(
        target=plot.id,
        model=PredefinedFit(name="power"),
        initial_values={"a": 1e-12, "b": -0.5},
    )
    document.push(add_fit(document.project, fit))
    document.push(refit(document.project, fit.id, document.data))
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    document.select(plot.id)

    def result():
        return next(
            a for a in document.figure.axes[0].artists if isinstance(a, FitCurve)
        ).result

    weighted = result()
    assert weighted.reduced_chi_square is not None
    panel.editors[("error_bars",)].widget.click()  # as a person does
    assert not _plot(document).error_bars
    assert result().reduced_chi_square is None, "still the weighted result"
    assert result() != weighted
    document.undo()
    assert result() == weighted  # one undo step takes both back


def test_the_fit_card_names_no_row_of_a_derived_series(qtbot, document) -> None:
    from figscribe.gui.properties import PropertyPanel

    plot = _plot(document)
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="power"))
    document.push(add_fit(document.project, fit))
    document.push(refit(document.project, fit.id, document.data))
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    document.select(fit.id)
    texts = [w.text() for w in panel.findChildren(type(panel._title))]
    assert any("Largest residual" in t for t in texts)
    assert not any("(row " in t for t in texts)
