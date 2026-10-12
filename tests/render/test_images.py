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
    ErrorbarPlot,
    Figure,
    GridLayout,
    Legend,
    LinePlot,
    ScatterPlot,
)
from figscribe.render import export

BASELINE = Path(__file__).parent / "baseline"
UPDATE = os.environ.get("FIGSCRIBE_UPDATE_BASELINES") == "1"

TOLERANCE = 0.5
"""RMS difference allowed, on Matplotlib's 0-255 scale.

Matplotlib's wheels bundle their own FreeType, so text renders the same on
every platform; the small tolerance absorbs antialiasing differences only.
"""


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
                            x=ref("t"), y=ref("dU"), linestyle="--", marker="o", label="noise"
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
                    artists=[ScatterPlot(x=ref("t"), y=ref("U"), color="C2", size=12.0)],
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
                Axes(y=AxisSpec(label="$U$", unit="V"), artists=[LinePlot(x=ref("t"), y=ref("U"))]),
                Axes(
                    row=1,
                    x=AxisSpec(label="$t$", unit="s"),
                    y=AxisSpec(label="$\\delta U$", unit="V"),
                    artists=[ScatterPlot(x=ref("t"), y=ref("dU"))],
                ),
            ],
        ),
    }


@pytest.mark.parametrize("name", ["line", "scatter", "errorbar", "two_panels"])
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

    assert expected.exists(), f"no baseline {expected.name}; run with FIGSCRIBE_UPDATE_BASELINES=1"
    failure = compare_images(str(expected), str(actual), tol=TOLERANCE)
    assert failure is None, failure
