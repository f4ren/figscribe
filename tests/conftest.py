"""Shared fixtures: a small but structurally complete example project."""

from __future__ import annotations

from datetime import datetime, timezone

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
        created=datetime(2026, 10, 12, tzinfo=timezone.utc),
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
