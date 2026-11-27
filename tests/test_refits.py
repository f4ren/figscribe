"""A fit follows what it was fitted to.

The window draws a fit's stored result, the generated script fits again: once
anything a fit is run on changes, the result has to change in the same step,
however the change is made.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from figscribe.codegen import generate
from figscribe.commands import SetField
from figscribe.fit import add_fit, refit
from figscribe.io import csv_source, load_data
from figscribe.io.refresh import read_differently, use_new_version
from figscribe.model import (
    AllanDeviationPlot,
    Axes,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    FitCurve,
    LinePlot,
    PredefinedFit,
    Project,
    Reduction,
    ScatterPlot,
    dumps,
    validate_references,
)
from figscribe.refits import DATA_FIELDS, INPUTS, LOOK_FIELDS, OWN_FIELDS
from figscribe.render import export
from figscribe.tools.operations import Toolbox
from figscribe.tools.workspace import ProjectWorkspace

T = np.linspace(0.0, 10.0, 41)


def _write(path: Path, height: float = 1.0) -> Path:
    """A peak U, a second one V beside it, and errors that differ by row."""
    rng = np.random.default_rng(3)
    u = height * np.exp(-((T - 4.0) ** 2) / 3.0) + rng.normal(0, 0.03, T.size)
    v = 0.6 * np.exp(-((T - 6.0) ** 2) / 5.0) + rng.normal(0, 0.03, T.size)
    du = 0.02 + 0.2 * (T / 10.0) ** 2
    table = np.column_stack([T, u, v, du])
    rows = [f"{a:g},{b:.5f},{c:.5f},{d:.4f}" for a, b, c, d in table]
    path.write_text("t,U,V,dU\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def _workspace(folder: Path) -> ProjectWorkspace:
    source = csv_source(_write(folder / "scan.csv"), folder)

    def col(name):
        return ColumnRef(source=source.id, column=name)

    plot = ErrorbarPlot(x=col("t"), y=col("U"), yerr=col("dU"), label="data")
    project = Project(sources=[source], figures=[Figure(axes=[Axes(artists=[plot])])])
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="gaussian"), label="fit")
    add_fit(project, fit).apply(project)
    refit(project, fit.id, load_data(project, folder)).apply(project)
    return ProjectWorkspace(project, folder)


def _parts(workspace):
    plot, fit = workspace.project.figures[0].axes[0].artists[:2]
    return workspace.project.sources[0], plot, fit


def _new_version(ws: ProjectWorkspace) -> None:
    _write(ws.base_dir / "scan.csv", height=2.0)
    ws.push(use_new_version(ws.project, _parts(ws)[0].id, ws.base_dir))


def _locate(ws: ProjectWorkspace) -> None:
    (ws.base_dir / "scan.csv").unlink()
    moved = ws.base_dir / "raw" / "scan.csv"
    moved.parent.mkdir()
    _write(moved, height=2.0)
    ws.push(use_new_version(ws.project, _parts(ws)[0].id, ws.base_dir, moved))


def _skip_rows(ws: ProjectWorkspace) -> None:
    source = _parts(ws)[0]
    ws.push(read_differently(ws.project, source.id, "skip_rows", 12, ws.base_dir))


def _set(part: int, name: str, value):
    def change(ws: ProjectWorkspace) -> None:
        obj = _parts(ws)[part]
        if name == "y":
            ws.push(
                SetField(obj.id, (name,), ColumnRef(source=obj.y.source, column=value))
            )
        else:
            ws.push(SetField(obj.id, (name,), value))

    return change


def _assistant(path: str, value):
    def change(ws: ProjectWorkspace) -> None:
        Toolbox(ws).call(
            "set_field",
            {"object_id": _parts(ws)[2].id, "path": [path], "value": value},
        )

    return change


CHANGES = {
    "new version": _new_version,
    "located": _locate,
    "reading": _skip_rows,
    "column": _set(1, "y", "V"),
    "errors off": _set(1, "yerr", None),
    "reduction": _set(1, "reduction", Reduction(count=4)),
    "x range": _set(1, "x_range", (1.0, 5.0)),
    "left out": _set(1, "left_out", [14, 15, 16, 17]),
    "fit range": _assistant("fit_range", [1.0, 5.0]),
    "model": _assistant("model", {"kind": "predefined", "name": "lorentzian"}),
    "held": _assistant("fixed", ["c"]),
}


@pytest.mark.parametrize("what", CHANGES)
def test_a_fit_is_run_again_in_the_same_step(tmp_path: Path, what: str) -> None:
    ws = _workspace(tmp_path)
    if what == "held":  # held at a start value that is not where the fit ends
        fit = _parts(ws)[2]
        fit.initial_values = {**fit.initial_values, "c": 0.2}
    before = dumps(ws.project)
    result = _parts(ws)[2].result
    CHANGES[what](ws)

    _, _, fit = _parts(ws)
    assert fit.result is not None and fit.result != result
    again = ws.project.model_copy(deep=True)
    refit(again, fit.id, load_data(again, ws.base_dir)).apply(again)
    new = again.figures[0].axes[0].artists[1].result
    assert fit.result.parameters == pytest.approx(new.parameters, rel=1e-6)
    ws.undo()  # one step
    assert dumps(ws.project) == before


def _assert_the_script_draws_the_same(ws: ProjectWorkspace) -> None:
    data = ws.data
    export(ws.project.figures[0], data, ws.base_dir / "window.png")
    script = generate(ws.project, base_dir=ws.base_dir, output="script.png", data=data)
    (ws.base_dir / "figure.py").write_text(script, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(ws.base_dir / "figure.py")],
        cwd=ws.base_dir,
        env={**os.environ, "MPLBACKEND": "Agg"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    a = np.asarray(Image.open(ws.base_dir / "window.png"))
    b = np.asarray(Image.open(ws.base_dir / "script.png"))
    assert np.array_equal(a, b), f"{np.count_nonzero(np.any(a != b, axis=-1))} pixels"


@pytest.mark.parametrize("what", CHANGES)
def test_the_script_draws_what_the_window_draws(tmp_path: Path, what: str) -> None:
    ws = _workspace(tmp_path)
    CHANGES[what](ws)
    _assert_the_script_draws_the_same(ws)


def test_a_fit_that_cannot_follow_is_left_unfitted(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    before = dumps(ws.project)
    ws.push(SetField(_parts(ws)[1].id, ("x_range",), (0.0, 0.3)))  # two points
    _, plot, fit = _parts(ws)
    assert plot.x_range == (0.0, 0.3) and fit.result is None
    problems = [str(i) for i in validate_references(ws.project, ws.data)]
    assert any("not fitted" in problem for problem in problems), problems
    ws.undo()
    assert dumps(ws.project) == before


def test_a_look_change_leaves_the_fit_alone(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    _, plot, fit = _parts(ws)
    fit.result = fit.result.model_copy(update={"reduced_chi_square": 123.0})
    for obj, name, value in ((plot, "color", "red"), (fit, "label", "model")):
        ws.push(SetField(obj.id, (name,), value))
    assert _parts(ws)[2].result.reduced_chi_square == 123.0  # not run again


def test_a_change_while_the_file_is_changed_leaves_the_fit(tmp_path: Path) -> None:
    """The data cannot be read then, which says nothing about the fit."""
    ws = _workspace(tmp_path)
    _write(tmp_path / "scan.csv", height=2.0)
    result = _parts(ws)[2].result
    ws.push(SetField(_parts(ws)[1].id, ("x_range",), (1.0, 5.0)))
    assert _parts(ws)[2].result == result


def test_every_field_is_known_to_matter_to_a_fit_or_not() -> None:
    """A new field has to be put in one list or the other."""
    for kind in (LinePlot, ScatterPlot, ErrorbarPlot, AllanDeviationPlot):
        unknown = set(kind.model_fields) - set(DATA_FIELDS) - set(LOOK_FIELDS)
        assert not unknown, (kind.__name__, unknown)
    assert set(FitCurve.model_fields) == set(INPUTS) | set(OWN_FIELDS)
