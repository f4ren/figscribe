"""Smoothing and normalising: the script computes what the preview does."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.fit import add_fit, refit
from figscribe.io import load_data
from figscribe.model import (
    AxisSpec,
    Conversion,
    ErrorBand,
    FitCurve,
    LinePlot,
    PredefinedFit,
    Reduction,
    Smoothing,
)
from tests.codegen.test_equivalence import _assert_same
from tests.test_process import made

CASES = {
    "savgol": {"smoothing": Smoothing(window=7, order=2)},
    "moving": {"smoothing": Smoothing(method="moving", window=5)},
    "left out and range": {
        "smoothing": Smoothing(window=5),
        "left_out": [4, 9],
        "x_range": (2.0, 15.0),
    },
    "conversion": {
        "smoothing": Smoothing(window=5),
        "x_conversion": Conversion(factor=1 / 60, unit="min"),
        "y_conversion": Conversion(factor=1000.0, unit="mV"),
    },
    "reduction": {
        "smoothing": Smoothing(method="moving", window=3),
        "reduction": Reduction(count=4),
        "left_out": [4],
    },
    "band": {"smoothing": Smoothing(window=5), "band": ErrorBand()},
}


@pytest.mark.parametrize("case", CASES)
def test_smoothed(tmp_path: Path, case: str) -> None:
    project, _, _ = made(tmp_path, **CASES[case])
    script = _assert_same(project, tmp_path)
    assert "_smooth" in script


def test_a_fit_and_residuals_of_smoothed_data_on_a_broken_axis(tmp_path) -> None:
    project, data, plot = made(tmp_path, smoothing=Smoothing(window=5))
    project.figures[0].axes[0].x = AxisSpec(breaks=[(8.0, 9.0)])
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    _assert_same(project, tmp_path)


def test_a_smoothed_line_beside_the_raw_one(tmp_path: Path) -> None:
    project, _, plot = made(tmp_path)
    smooth = LinePlot(x=plot.x, y=plot.y, smoothing=Smoothing(), color="C3")
    project.figures[0].axes[0].artists.append(smooth)
    script = _assert_same(project, tmp_path)
    assert script.count("savgol_filter(") == 1
