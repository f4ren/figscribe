"""Roadmap task B7.1: awkward data, from import to the generated script.

Every plot type meets every awkward case: no rows, nothing but NaN, one or
two points, constant values, values at or below zero on a log axis, tiny and
huge numbers, integers, and reversed or equal axis ranges. Each step may
refuse with figscribe's own message (DataError, FitError, CommandError);
anything else is a crash. What figscribe draws, its script must draw too.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

from figscribe.codegen import generate
from figscribe.commands import CommandError, History, SetField
from figscribe.fit import FitError, add_fit, refit
from figscribe.io import DataError, csv_source, load_data
from figscribe.io.numpyfile import numpy_source
from figscribe.model import (
    ArrayRef,
    Axes,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    FitCurve,
    Histogram,
    ImagePlot,
    LinePlot,
    PredefinedFit,
    Project,
    ScatterPlot,
    validate_references,
)
from figscribe.render import export
from figscribe.render.figure import render

OWN = (DataError, FitError, CommandError)
"""Refusals that carry a message written for the user."""

_X = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]

CASES: dict[str, dict] = {
    "no rows": {"x": [], "y": []},
    "only NaN": {"x": _X, "y": [math.nan] * 8},
    "one point": {"x": [1.0], "y": [2.0]},
    "two points": {"x": [1.0, 2.0], "y": [2.0, 3.0]},
    "constant": {"x": _X, "y": [3.0] * 8},
    "zero and below on a log axis": {
        "x": _X,
        "y": [-2.0, -1.0, 0.0, 1.0, 2.0, 4.0, 8.0, 16.0],
        "scale": "log",
    },
    "tiny": {"x": _X, "y": [1e-30 * (1 + i) for i in range(8)]},
    "huge": {"x": _X, "y": [1e30 * (1 + i) for i in range(8)]},
    "integers": {"x": list(range(8)), "y": [3, 1, 4, 1, 5, 9, 2, 6]},
    "reversed range": {"x": _X, "y": [1.0, 2.0] * 4, "limits": (10.0, 0.0)},
    "equal range": {"x": _X, "y": [1.0, 2.0] * 4, "limits": (5.0, 5.0)},
}

KINDS = ["line", "points", "error bars", "histogram", "fit"]

SAID = {
    "only NaN": "has no values to draw",
    "zero and below on a log axis": "are zero or below",
    "zero and below with a log scale": "are zero or below",
}
"""Cases that draw, but not everything: the problem list must say what."""


def _number(value) -> str:
    return "nan" if isinstance(value, float) and math.isnan(value) else repr(value)


def _write_csv(folder: Path, case: dict) -> Path:
    rows = ["x,y,dy"] + [
        f"{_number(x)},{_number(y)},0.1"
        for x, y in zip(case["x"], case["y"], strict=True)
    ]
    path = folder / "data.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _plot(kind: str, source_id: str):
    def col(name: str) -> ColumnRef:
        return ColumnRef(source=source_id, column=name)

    if kind == "line":
        return LinePlot(x=col("x"), y=col("y"))
    if kind == "points":
        return ScatterPlot(x=col("x"), y=col("y"))
    if kind == "histogram":
        return Histogram(values=col("y"))
    return ErrorbarPlot(x=col("x"), y=col("y"), yerr=col("dy"))


def _build(folder: Path, kind: str, case: dict) -> Project:
    """The project, with every step that may refuse already taken; raises
    one of OWN for a refusal."""
    path = _write_csv(folder, case)
    source = csv_source(path, folder, header_row=0, skip_rows=0)
    plot = _plot(kind, source.id)
    figure = Figure(dpi=72, axes=[Axes(artists=[plot])])
    project = Project(figscribe_version="test", sources=[source], figures=[figure])
    history = History(project)
    axes = figure.axes[0]
    if "scale" in case:
        history.push(SetField(axes.id, ("y", "scale"), case["scale"]))
    if "limits" in case:
        history.push(SetField(axes.id, ("y", "limits"), case["limits"]))
    if kind == "fit":
        fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"))
        history.push(add_fit(project, fit))
        history.push(refit(project, fit.id, load_data(project, folder)))
    return project


def _outcome(folder: Path, project: Project, case: str = "") -> str:
    """Draw, export and run the script; "refused: ..." or "drawn"."""
    figure = project.figures[0]
    data = load_data(project, folder)
    if case in SAID:
        problems = [str(issue) for issue in validate_references(project, data)]
        assert any(SAID[case] in p for p in problems), problems
    try:
        FigureCanvasAgg(render(figure, data)).draw()
        export(figure, data, folder / "figure.pdf")
        export(figure, data, folder / "figure.png")
    except OWN as exc:
        return f"refused: {exc}"
    script = generate(project, figure, base_dir=folder, output="script.png", data=data)
    path = folder / "script.py"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(path)],
        cwd=folder,
        env={**os.environ, "MPLBACKEND": "Agg"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, f"figscribe drew it, its script failed:\n{done.stderr}"
    return "drawn"


@pytest.mark.slow
@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("kind", KINDS)
def test_awkward_columns(tmp_path: Path, kind: str, case: str) -> None:
    try:
        project = _build(tmp_path, kind, CASES[case])
    except OWN:
        return  # refused, in words written for the user
    if kind == "histogram" and "log" in case:
        case = ""  # the values lie along x; the y axis counts them
    _outcome(tmp_path, project, case)


IMAGES: dict[str, np.ndarray] = {
    "no pixels": np.zeros((0, 0)),
    "one pixel": np.ones((1, 1)),
    "only NaN": np.full((4, 5), np.nan),
    "constant": np.full((4, 5), 2.0),
    "zero and below with a log scale": np.arange(-5.0, 15.0).reshape(4, 5),
    "huge": np.full((4, 5), 1e30) * np.arange(1, 21).reshape(4, 5),
    "integers": np.arange(20).reshape(4, 5),
}


@pytest.mark.slow
@pytest.mark.parametrize("case", IMAGES)
def test_awkward_images(tmp_path: Path, case: str) -> None:
    try:
        np.save(tmp_path / "map.npy", IMAGES[case])
        source = numpy_source(tmp_path / "map.npy", tmp_path)
        norm = "log" if "log" in case else "linear"
        image = ImagePlot(data=ArrayRef(source=source.id), norm=norm)
        project = Project(
            figscribe_version="test",
            sources=[source],
            figures=[Figure(dpi=72, axes=[Axes(artists=[image])])],
        )
    except OWN:
        return
    _outcome(tmp_path, project, case)
