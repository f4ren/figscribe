"""Shared fixtures: a small but structurally complete example project, and a
writable copy of the example project on disk."""

from __future__ import annotations

import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from figscribe.model import (
    Axes,
    AxisSpec,
    ColumnRef,
    CsvSource,
    ErrorbarPlot,
    Figure,
    FitCurve,
    FitResult,
    GridLayout,
    Legend,
    PredefinedFit,
    Project,
    ResidualPlot,
)

# GUI tests run without a display; set before any test creates the QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EXAMPLE = Path(__file__).parents[1] / "examples" / "gaussian-scan"


@pytest.fixture
def example(tmp_path: Path) -> Path:
    """A writable copy of the example project; returns its project file."""
    target = tmp_path / "gaussian-scan"
    shutil.copytree(EXAMPLE, target)
    return target / "scan.figscribe"


@pytest.fixture
def source() -> CsvSource:
    return CsvSource(
        path="examples/scan.csv",
        sha256="0" * 64,
        columns=["t", "U", "dU"],
    )


@pytest.fixture
def project(source: CsvSource) -> Project:
    """A two-panel figure: data with a fit on top, residuals below."""

    def ref(column: str) -> ColumnRef:
        return ColumnRef(source=source.id, column=column)

    data = ErrorbarPlot(x=ref("t"), y=ref("U"), yerr=ref("dU"), label="measurement")
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="gaussian"),
        initial_values={"a": 1.0, "mu": 0.0, "sigma": 1.0},
        result=FitResult(
            parameters={"a": 1.02},
            uncertainties={"a": 0.03},
            reduced_chi_square=0.97,
        ),
        label="Gaussian fit",
    )
    residuals = ResidualPlot(target=fit.id)

    return Project(
        figscribe_version="0.0.2",
        created=datetime(2026, 10, 12, tzinfo=UTC),
        sources=[source],
        figures=[
            Figure(
                name="Scan",
                width_mm=85.0,
                layout=GridLayout(
                    rows=2, cols=1, share_x="col", height_ratios=[3.0, 1.0]
                ),
                axes=[
                    Axes(
                        row=0,
                        col=0,
                        x=AxisSpec(label=r"$t$", unit="s"),
                        y=AxisSpec(label=r"$U$", unit="V"),
                        legend=Legend(visible=True, position=(0.6, 0.9)),
                        artists=[data, fit],
                    ),
                    Axes(
                        row=1,
                        col=0,
                        x=AxisSpec(label=r"$t$", unit="s"),
                        y=AxisSpec(label="residual"),
                        artists=[residuals],
                    ),
                ],
            )
        ],
    )


@pytest.fixture(autouse=True)
def _leave_the_clipboard_to_qt():
    """A figure copied to the clipboard is made in Python; Qt would delete it
    only when the process ends, after Python has shut down, and crash. The
    program does this when it quits."""
    yield
    clipboard = sys.modules.get("figscribe.gui.clipboard")
    if clipboard is not None:
        clipboard.release()
