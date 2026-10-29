"""Test 3 from the project brief: image regression against reference images.

Reference images live in tests/render/baseline/. After an intended change to
the rendering, regenerate them with

    FIGSCRIBE_UPDATE_BASELINES=1 pytest tests/render/test_images.py

and review the new images before committing them.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib
import pytest
from matplotlib.testing.compare import compare_images

from figscribe.model import (
    Axes,
    AxisSpec,
    Conversion,
    ErrorBand,
    ErrorbarPlot,
    Figure,
    FitCurve,
    FitResult,
    GridLayout,
    Legend,
    LinePlot,
    PanelLabels,
    PredefinedFit,
    ReferenceLine,
    ResidualPlot,
    ScatterPlot,
    ShadedSpan,
)
from figscribe.render import export

BASELINE = Path(__file__).parent / "baseline"
UPDATE = os.environ.get("FIGSCRIBE_UPDATE_BASELINES") == "1"

TOLERANCE = 0.5
"""RMS difference allowed, on Matplotlib's 0-255 scale.

Matplotlib's wheels bundle their own FreeType, so text renders the same on
every platform; the small tolerance absorbs antialiasing differences only.
"""


def _residuals_figure(ref) -> Figure:
    """A fit with its residuals below, drawn thick and with a red zero line."""
    data = ErrorbarPlot(x=ref("t"), y=ref("U"), yerr=ref("dU"), linestyle="none")
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="linear"),
        result=FitResult(parameters={"a": 0.05, "b": 0.0}, uncertainties={}),
    )
    residuals = ResidualPlot(
        target=fit.id,
        color="tab:blue",
        linestyle="-",
        linewidth=2.5,
        zero_color="tab:red",
        zero_linewidth=1.5,
        zero_linestyle="-",
    )
    return Figure(
        dpi=100.0,
        layout=GridLayout(rows=2),
        axes=[
            Axes(x=AxisSpec(label="$t$", unit="s"), artists=[data, fit]),
            Axes(row=1, y=AxisSpec(label="Residual"), artists=[residuals]),
        ],
    )


def _figures(ref) -> dict[str, Figure]:
    labelled = {
        "x": AxisSpec(label="$t$", unit="s"),
        "y": AxisSpec(label="$U$", unit="V"),
    }
    return {
        "line": Figure(
            dpi=100.0,
            axes=[
                Axes(
                    **labelled,
                    legend=Legend(visible=True),
                    artists=[
                        LinePlot(x=ref("t"), y=ref("U"), label="signal"),
                        LinePlot(
                            x=ref("t"),
                            y=ref("dU"),
                            linestyle="--",
                            marker="o",
                            label="noise",
                        ),
                    ],
                )
            ],
        ),
        "scatter": Figure(
            dpi=100.0,
            axes=[
                Axes(
                    x=labelled["x"],
                    y=AxisSpec(label="$U$", unit="V", scale="log"),
                    artists=[
                        ScatterPlot(x=ref("t"), y=ref("U"), color="C2", size=12.0)
                    ],
                )
            ],
        ),
        "errorbar": Figure(
            dpi=100.0,
            axes=[
                Axes(
                    **labelled,
                    grid=True,
                    artists=[ErrorbarPlot(x=ref("t"), y=ref("U"), yerr=ref("dU"))],
                )
            ],
        ),
        "two_panels": Figure(
            dpi=100.0,
            height_mm=80.0,
            layout=GridLayout(rows=2, share_x="all", height_ratios=[3.0, 1.0]),
            axes=[
                Axes(
                    y=AxisSpec(label="$U$", unit="V"),
                    artists=[LinePlot(x=ref("t"), y=ref("U"))],
                ),
                Axes(
                    row=1,
                    x=AxisSpec(label="$t$", unit="s"),
                    y=AxisSpec(label="$\\delta U$", unit="V"),
                    artists=[ScatterPlot(x=ref("t"), y=ref("dU"))],
                ),
            ],
        ),
        "panel_labels": Figure(
            dpi=100.0,
            width_mm=120.0,
            layout=GridLayout(cols=2),
            panel_labels=PanelLabels(bold=True),
            axes=[
                Axes(**labelled, artists=[LinePlot(x=ref("t"), y=ref("U"))]),
                Axes(
                    col=1,
                    **labelled,
                    title="Noise",
                    artists=[ScatterPlot(x=ref("t"), y=ref("dU"))],
                ),
            ],
        ),
        "reference_lines": Figure(
            dpi=100.0,
            axes=[
                Axes(
                    **labelled,
                    grid=True,
                    legend=Legend(visible=True),
                    artists=[
                        ErrorbarPlot(x=ref("t"), y=ref("U"), yerr=ref("dU")),
                        ReferenceLine(at=5.0, label="centre"),
                        ReferenceLine(
                            orientation="horizontal", at=0.5, color="C3", linestyle=":"
                        ),
                        ShadedSpan(start=3.5, end=6.5, label="peak"),
                        ShadedSpan(
                            orientation="horizontal", start=0.8, end=1.0, color="C2"
                        ),
                    ],
                )
            ],
        ),
        "converted": Figure(
            dpi=100.0,
            axes=[
                Axes(
                    x=AxisSpec(label="$t$", unit="min"),
                    y=AxisSpec(label="$U$", unit="mV"),
                    artists=[
                        ErrorbarPlot(
                            x=ref("t"),
                            y=ref("U"),
                            yerr=ref("dU"),
                            x_conversion=Conversion(factor=1 / 60, unit="min"),
                            y_conversion=Conversion(factor=1000.0, unit="mV"),
                            x_range=(0.03, 0.15),
                            left_out=[8],
                        ),
                    ],
                )
            ],
        ),
        "error_band": Figure(
            dpi=100.0,
            axes=[
                Axes(
                    **labelled,
                    legend=Legend(visible=True),
                    artists=[
                        ErrorbarPlot(
                            x=ref("t"),
                            y=ref("U"),
                            yerr=ref("dU"),
                            linestyle="-",
                            marker="none",
                            label="signal",
                            left_out=[14],
                            band=ErrorBand(),
                        ),
                    ],
                )
            ],
        ),
        "residuals": _residuals_figure(ref),
    }


@pytest.mark.parametrize(
    "name",
    [
        "line",
        "scatter",
        "errorbar",
        "two_panels",
        "panel_labels",
        "reference_lines",
        "error_band",
        "converted",
        "residuals",
    ],
)
def test_matches_baseline(name: str, ref, data, tmp_path: Path) -> None:
    figure = _figures(ref)[name]
    expected = BASELINE / f"{name}.png"
    actual = tmp_path / f"{name}.png"

    # Isolate from any matplotlibrc on the machine running the tests.
    with matplotlib.style.context("default"):
        export(figure, data, actual)

    if UPDATE:
        BASELINE.mkdir(exist_ok=True)
        expected.write_bytes(actual.read_bytes())
        pytest.skip(f"baseline {expected.name} updated")

    assert expected.exists(), (
        f"no baseline {expected.name}; run with FIGSCRIBE_UPDATE_BASELINES=1"
    )
    failure = compare_images(str(expected), str(actual), tol=TOLERANCE)
    assert failure is None, failure
