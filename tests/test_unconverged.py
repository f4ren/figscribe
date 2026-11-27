"""A fit that did not converge (B10.1) and units of an own formula (B10.2).

Its parameters are only where curve_fit started, and curve_fit stops there with
an error, so neither the window nor the script may draw it.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

import figscribe.fit.run
from figscribe.codegen import generate
from figscribe.commands import History
from figscribe.fit import add_fit, refit, residuals, set_left_out
from figscribe.io import csv_source, load_data
from figscribe.model import (
    Axes,
    ColumnRef,
    Conversion,
    ExpressionFit,
    Figure,
    FitCurve,
    FitResult,
    LinePlot,
    PredefinedFit,
    Project,
    ResidualPlot,
    validate_references,
)
from figscribe.render import render
from figscribe.tools.workspace import ProjectWorkspace
from figscribe.units import set_conversion, set_range

T = np.linspace(0.0, 10.0, 21)


def _project(tmp_path: Path, model=None, start=None) -> Project:
    rows = "\n".join(f"{t:g},{0.5 * t + 1:g}" for t in T)
    (tmp_path / "d.csv").write_text("t,U\n" + rows + "\n", encoding="utf-8")
    source = csv_source(tmp_path / "d.csv", tmp_path)

    def col(name):
        return ColumnRef(source=source.id, column=name)

    plot = LinePlot(x=col("t"), y=col("U"), label="data")
    project = Project(sources=[source], figures=[Figure(axes=[Axes(artists=[plot])])])
    fit = FitCurve(
        target=plot.id,
        model=model or PredefinedFit(name="linear"),
        initial_values=start or {},
        label="fit",
    )
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    return project


def _parts(project: Project):
    plot, fit = project.figures[0].axes[0].artists[:2]
    return plot, fit


def _give_up(project: Project) -> None:
    fit = _parts(project)[1]
    fit.result = FitResult(
        parameters={"a": 9.0, "b": -3.0},
        uncertainties={"a": math.inf, "b": math.inf},
        converged=False,
    )


def _lines(figure, gid: str) -> list:
    return [line for ax in figure.axes for line in ax.lines if line.get_gid() == gid]


def test_a_fit_that_gave_up_is_drawn_nowhere(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _give_up(project)
    _, fit = _parts(project)
    below = project.figures[0].axes[1].artists[0]
    assert isinstance(below, ResidualPlot)
    figure = render(project.figures[0], load_data(project, tmp_path))
    FigureCanvasAgg(figure).draw()
    assert _lines(figure, fit.id) == []
    assert not any(c.get_label() == "fit" for ax in figure.axes for c in ax.containers)
    assert all(line.get_gid() != below.id for ax in figure.axes for line in ax.lines)

    script = generate(project, base_dir=tmp_path, data=load_data(project, tmp_path))
    assert "curve_fit(" not in script and "did not converge" in script
    problems = [
        str(i) for i in validate_references(project, load_data(project, tmp_path))
    ]
    assert any("did not converge" in p and "no curve" in p for p in problems)


def _gives_up(*args, **kwargs):
    raise RuntimeError("Optimal parameters not found")


@pytest.mark.parametrize("edit", ["left out", "range", "units"])
def test_an_edit_that_fits_again_leaves_it_unfitted(
    tmp_path: Path, monkeypatch, edit: str
) -> None:
    project = _project(tmp_path)
    plot, fit = _parts(project)
    start = dict(fit.initial_values)
    data = load_data(project, tmp_path)
    monkeypatch.setattr(figscribe.fit.run, "curve_fit", _gives_up)
    if edit == "left out":
        command = set_left_out(project, plot.id, [3], data)
    elif edit == "range":
        command = set_range(project, plot.id, (1.0, 9.0), data)
    else:
        command = set_conversion(
            project, plot.id, "x", Conversion(factor=60.0, unit="s"), data
        )
    History(project).push(command)
    plot, fit = _parts(project)
    assert fit.result is None
    if edit != "units":  # a unit change drops what the model can guess anew
        assert fit.initial_values == start


GAUSS = ExpressionFit(expression="a * exp(-(x - m)**2 / s)", parameters=["a", "m", "s"])


def _peak(tmp_path: Path) -> Project:
    project = _project(tmp_path)
    rows = "\n".join(f"{t:g},{math.exp(-((t - 4) ** 2) / 3):.6f}" for t in T)
    (tmp_path / "p.csv").write_text("t,U\n" + rows + "\n", encoding="utf-8")
    source = csv_source(tmp_path / "p.csv", tmp_path)
    plot = LinePlot(
        x=ColumnRef(source=source.id, column="t"),
        y=ColumnRef(source=source.id, column="U"),
    )
    project = Project(sources=[source], figures=[Figure(axes=[Axes(artists=[plot])])])
    fit = FitCurve(
        target=plot.id, model=GAUSS, initial_values={"a": 1.0, "m": 4.0, "s": 3.0}
    )
    add_fit(project, fit).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    return project


def test_a_unit_change_keeps_the_start_values_of_an_own_formula(
    tmp_path: Path,
) -> None:
    """From ones it "converged" to nonsense. From the values it had, with x a
    thousand times larger, the data do not decide the parameters: not fitted."""
    project = _peak(tmp_path)
    plot, fit = _parts(project)
    start = dict(fit.initial_values)
    data = load_data(project, tmp_path)
    ms = Conversion(factor=1000.0, unit="ms")
    History(project).push(set_conversion(project, plot.id, "x", ms, data))
    plot, fit = _parts(project)
    assert plot.x_conversion == ms  # never refused
    assert fit.result is None and fit.initial_values == start


def test_a_unit_change_fits_an_own_formula_that_can_be_fitted(
    tmp_path: Path,
) -> None:
    project = _peak(tmp_path)
    plot, fit = _parts(project)
    data = load_data(project, tmp_path)
    mV = Conversion(factor=1000.0, unit="mV")  # y: only the height grows
    History(project).push(set_conversion(project, plot.id, "y", mV, data))
    fit = _parts(project)[1]
    assert fit.result.parameters["a"] == pytest.approx(1000.0, rel=1e-3)
    assert fit.result.parameters["m"] == pytest.approx(4.0, rel=1e-3)


# --- through the window's push, where the refit rule has its say too ----------


def _workspace(project: Project, folder: Path) -> ProjectWorkspace:
    return ProjectWorkspace(project, folder)


def _ms(ws: ProjectWorkspace, plot, data) -> None:
    ms = Conversion(factor=1000.0, unit="ms")
    ws.push(set_conversion(ws.project, plot.id, "x", ms, data))


def test_a_formula_left_unfitted_is_not_fitted_to_nonsense_later(
    tmp_path: Path,
) -> None:
    """Its start values are in the old units: no edit may draw them as a fit."""
    ws = _workspace(_peak(tmp_path), tmp_path)
    plot, _ = _parts(ws.project)
    _ms(ws, plot, ws.data)
    assert _parts(ws.project)[1].result is None
    mV = Conversion(factor=1000.0, unit="mV")
    ws.push(set_conversion(ws.project, plot.id, "y", mV, ws.data))
    assert _parts(ws.project)[1].result is None
    ws.push(set_left_out(ws.project, plot.id, [20], ws.data))
    assert _parts(ws.project)[1].result is None
    ws.push(set_range(ws.project, plot.id, (0.0, 9000.0), ws.data))
    assert _parts(ws.project)[1].result is None


@pytest.mark.parametrize("factor", [1000.0, 60.0, 1e6])
def test_an_unfitted_predefined_model_is_guessed_after_a_unit_change(
    tmp_path: Path, factor: float
) -> None:
    project = _peak(tmp_path)
    plot, fit = _parts(project)
    fit.model = PredefinedFit(name="gaussian")
    fit.initial_values = {"a": 1.0, "mu": 4.0, "sigma": 1.2, "c": 0.0}
    fit.result = None
    ws = _workspace(project, tmp_path)
    scaled = Conversion(factor=factor, unit="u")
    ws.push(set_conversion(ws.project, plot.id, "x", scaled, ws.data))
    fit = _parts(ws.project)[1]
    assert fit.result is not None
    assert fit.result.parameters["mu"] == pytest.approx(4 * factor, rel=1e-3)


def test_a_unit_change_leaves_no_start_values_of_the_old_units(
    tmp_path: Path, monkeypatch
) -> None:
    """Where the guess fails, the values of before must not be tried in their
    stead: they are in the old units. Only held ones stay (0041)."""
    project = _project(tmp_path)
    plot, fit = _parts(project)
    old = {"a": 0.4, "b": 0.9}
    fit.initial_values = dict(old)
    fit.result = None
    real = figscribe.fit.run.curve_fit

    def only_from_the_old(*args, **kwargs):
        if np.allclose(kwargs["p0"], list(old.values())):
            return real(*args, **kwargs)
        raise RuntimeError("Optimal parameters not found")

    monkeypatch.setattr(figscribe.fit.run, "curve_fit", only_from_the_old)
    ws = _workspace(project, tmp_path)
    _ms(ws, plot, ws.data)
    fit = _parts(ws.project)[1]
    assert fit.result is None and fit.initial_values == {}
    ws.undo()
    assert _parts(ws.project)[1].initial_values == old


@pytest.mark.parametrize("degree", [3, None])
def test_a_predefined_model_is_kept_though_its_parameters_depend(
    tmp_path: Path, monkeypatch, degree
) -> None:
    """A polynomial in kelvin: fitted well, but its uncertainties unknown."""
    model = (
        PredefinedFit(name="polynomial", degree=degree)
        if degree
        else PredefinedFit(name="linear")
    )
    project = _project(tmp_path, model=model)
    plot, fit = _parts(project)
    known = dict.fromkeys(fit.result.uncertainties, 0.1)  # decided before
    fit.result = fit.result.model_copy(update={"uncertainties": known})
    real = figscribe.fit.run.curve_fit

    def unknown(*args, **kwargs):
        popt, pcov = real(*args, **kwargs)
        return popt, np.full_like(pcov, np.inf)

    monkeypatch.setattr(figscribe.fit.run, "curve_fit", unknown)
    ws = _workspace(project, tmp_path)
    kelvin = Conversion(formula="x + 273.15", unit="K")
    ws.push(set_conversion(ws.project, plot.id, "x", kelvin, ws.data))
    assert _parts(ws.project)[1].result is not None


def test_a_result_drawn_nowhere_refuses_no_edit(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _give_up(project)
    plot = _parts(project)[0]
    ws = _workspace(project, tmp_path)
    ws.push(set_range(ws.project, plot.id, (0.0, 0.6), ws.data))  # two points
    assert _parts(ws.project)[1].result is None


@pytest.mark.parametrize("factor", [2.0, 1000.0, 0.001])
def test_a_formula_on_exact_data_stays_fitted_across_units(
    tmp_path: Path, monkeypatch, factor: float
) -> None:
    """Without noise the uncertainties may be unknown before and after: the
    change has made nothing worse."""
    line = ExpressionFit(expression="a * x + b", parameters=["a", "b"])
    project = _project(tmp_path, model=line, start={"a": 0.5, "b": 1.0})
    plot, fit = _parts(project)
    fit.result = fit.result.model_copy(
        update={"uncertainties": {"a": math.inf, "b": math.inf}}
    )
    real = figscribe.fit.run.curve_fit

    def unknown(*args, **kwargs):
        popt, pcov = real(*args, **kwargs)
        return popt, np.full_like(pcov, np.inf)

    monkeypatch.setattr(figscribe.fit.run, "curve_fit", unknown)
    ws = _workspace(project, tmp_path)
    scaled = Conversion(factor=factor, unit="u")
    ws.push(set_conversion(ws.project, plot.id, "y", scaled, ws.data))
    assert _parts(ws.project)[1].result is not None


def test_a_fit_drawn_nowhere_has_no_residuals_and_one_problem(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    _give_up(project)
    data = load_data(project, tmp_path)
    _, fit = _parts(project)
    assert residuals(project, fit.id, data) is None
    fit.fit_range = (100.0, 200.0)  # no point at all
    problems = [str(i) for i in validate_references(project, data)]
    assert len([p for p in problems if "artists[1]" in p]) == 1, problems
