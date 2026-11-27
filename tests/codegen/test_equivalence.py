"""The core promise: the generated script draws exactly what the renderer draws.

For every project here, the renderer's PNG and the PNG written by the
generated script, run in a separate Python process, must be pixel-identical.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from figscribe.assistant import bench
from figscribe.codegen import generate
from figscribe.commands import add_panel
from figscribe.fit import add_fit, refit
from figscribe.io import load_data
from figscribe.io.csvfile import csv_source
from figscribe.model import (
    AllanDeviationPlot,
    Axes,
    AxisSpec,
    ColumnRef,
    Conversion,
    ErrorBand,
    ErrorbarPlot,
    ExpressionFit,
    Figure,
    FitCurve,
    GridLayout,
    Histogram,
    Legend,
    LinePlot,
    PanelLabels,
    PredefinedFit,
    Project,
    Reduction,
    ReferenceLine,
    ResidualPlot,
    ScatterPlot,
    ShadedSpan,
    loads,
)
from figscribe.render import export

EXAMPLES = sorted((Path(__file__).parents[2] / "examples").glob("*/*.figscribe"))


def _run(script: str, folder: Path) -> Path:
    path = folder / "figure_script.py"
    path.write_text(script, encoding="utf-8")
    env = {**os.environ, "MPLBACKEND": "Agg"}
    done = subprocess.run(
        [sys.executable, "-I", str(path)],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return folder / "from_script.png"


def _assert_same(project: Project, folder: Path, figure: Figure | None = None) -> str:
    figure = figure or project.figures[0]
    data = load_data(project, folder)
    export(figure, data, folder / "from_renderer.png")
    script = generate(
        project,
        figure,
        base_dir=folder,
        output="from_script.png",
        data=data,
    )
    assert "import figscribe" not in script and "from figscribe" not in script
    produced = _run(script, folder)
    a = np.asarray(Image.open(folder / "from_renderer.png"))
    b = np.asarray(Image.open(produced))
    assert a.shape == b.shape
    assert np.array_equal(a, b), f"{np.count_nonzero(np.any(a != b, axis=-1))} pixels"
    return script


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(
            p, marks=[] if p.parent.name == "gaussian-scan" else pytest.mark.slow
        )
        for p in EXAMPLES
    ],
    ids=lambda p: p.parent.name,
)
def test_examples(path: Path, tmp_path: Path) -> None:
    folder = tmp_path / path.parent.name
    shutil.copytree(path.parent, folder)
    project = loads((folder / path.name).read_text(encoding="utf-8"))
    for figure in project.figures:
        _assert_same(project, folder, figure)


# --- built projects -----------------------------------------------------------


def _scan(folder: Path) -> tuple[Project, dict[str, ColumnRef]]:
    t = np.linspace(0.0, 10.0, 41)
    rng = np.random.default_rng(1)
    u = np.exp(-((t - 5.0) ** 2) / 2.8) + rng.normal(0, 0.03, t.size)
    rows = "\n".join(
        f"{a:.3f},{b:.5f},0.030,{a * a:.4f}" for a, b in zip(t, u, strict=True)
    )
    (folder / "scan.csv").write_text(f"t,U,dU,t2\ns,V,V,s2\n{rows}\n", encoding="utf-8")
    source = csv_source(folder / "scan.csv", folder, header_row=0, skip_rows=1)
    refs = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    return Project(figscribe_version="test", sources=[source]), refs


def test_fit_and_residuals(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="data")
    figure = Figure(
        dpi=150,
        axes=[
            Axes(
                x=AxisSpec(label="$t$", unit="s"),
                y=AxisSpec(label="$U$", unit="V"),
                legend=Legend(visible=True),
                artists=[data],
            )
        ],
    )
    project.figures = [figure]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"), label="fit")
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "curve_fit(" in script and "sharex=ax_a" in script
    assert 'ax_a.tick_params(axis="x"' in script


@pytest.mark.parametrize(
    ("x", "curve", "written"),
    [
        ({}, {"curve_range": (-3.0, 15.0)}, "np.linspace(-3.0, 15.0, 400)"),
        (
            {"limits": (16.0, -2.0)},
            {"curve_to_limits": True},
            "np.linspace(-2.0, 16.0, 400)",
        ),
        ({"limits": (0.0, 12.0)}, {"curve_range": (2.0, 4.0)}, "linspace(2.0, 4.0"),
        (
            {"scale": "log"},
            {"curve_range": (0.5, 100.0)},
            "np.geomspace(0.5, 100.0, 400)",
        ),
        (
            {"breaks": [(11.0, 18.0)]},
            {"curve_range": (0.0, 22.0)},
            "np.linspace(18.0, 22.0",
        ),
        (
            {"breaks": [(11.0, 18.0)], "limits": (-1.0, 22.0)},
            {"curve_to_limits": True, "fit_range": (3.0, 7.0)},
            "np.linspace(-1.0, 11.0",
        ),
    ],
    ids=["range", "limits", "shorter", "log", "break", "break-limits"],
)
def test_a_curve_beyond_the_data(tmp_path: Path, x, curve, written) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="data")
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"), **curve)
    panel = Axes(x=AxisSpec(**x), artists=[data])
    project.figures = [Figure(dpi=110, axes=[panel])]
    add_fit(project, fit, residuals=False).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert written in script
    assert [line for line in script.splitlines() if len(line) > 88] == []


@pytest.mark.parametrize(
    "curve",
    [
        {"curve_range": (-3.0, 15.0)},
        {"curve_range": (-3.0, 15.0), "extrapolated_linestyle": ":"},
        {"curve_range": (-3.0, 15.0), "mark_extrapolated": False},
        {"curve_range": (-3.0, 15.0), "extrapolated_color": "red"},
        {"curve_range": (-3.0, 15.0), "extrapolated_linewidth": 3.0},
        {"curve_range": (4.0, 15.0)},  # leaves the data on one side only
        {"curve_range": (12.0, 15.0)},  # nowhere on them
        {"curve_range": (2.0, 8.0)},  # never leaves them
    ],
    ids=["dashed", "dotted", "unmarked", "color", "width", "one-side", "away", "in"],
)
@pytest.mark.parametrize("known", [True, False], ids=["data", "no-data"])
def test_the_extrapolated_part_of_a_curve(tmp_path: Path, curve, known) -> None:
    """In the cycle's colors, which the two parts of the curve share: the plot
    after them keeps its own."""
    project, ref = _scan(tmp_path)
    data = LinePlot(x=ref["t"], y=ref["U"], linestyle="none", marker="o")
    fit = FitCurve(
        target=data.id, model=PredefinedFit(name="gaussian"), label="fit", **curve
    )
    panel = Axes(legend=Legend(visible=True), artists=[data])
    project.figures = [Figure(dpi=110, axes=[panel])]
    add_fit(project, fit, residuals=False).apply(project)
    values = load_data(project, tmp_path)
    refit(project, fit.id, values).apply(project)
    project.figures[0].axes[0].artists.append(LinePlot(x=ref["t"], y=ref["U"]))
    export(project.figures[0], values, tmp_path / "from_renderer.png")
    script = generate(
        project,
        base_dir=tmp_path,
        output="from_script.png",
        data=values if known else None,
    )
    a = np.asarray(Image.open(tmp_path / "from_renderer.png"))
    b = np.asarray(Image.open(_run(script, tmp_path)))
    assert np.array_equal(a, b), f"{np.count_nonzero(np.any(a != b, axis=-1))} pixels"
    assert [line for line in script.splitlines() if len(line) > 88] == []
    if known:
        marked = curve["curve_range"] != (2.0, 8.0) and curve.get(
            "mark_extrapolated", True
        )
        assert ("beyond" in script) == marked
        # A color of its own is written plainly, not taken from the curve.
        assert ("get_color()" in script) == (
            marked and "extrapolated_color" not in curve
        )


@pytest.mark.parametrize("x_breaks", [[], [(11.0, 12.0)]], ids=["whole", "broken"])
def test_columns_named_like_the_scripts_own_variables(tmp_path: Path, x_breaks) -> None:
    """The names the script makes for a curve beyond the data must not take a
    column's."""
    names = ["t", "U", "t_first", "t_last", "t_fit", "t_fit_y", "t_fit_measured"]
    names += ["t_fit_beyond", "t_fit_line"]
    t = np.linspace(0.0, 10.0, 21)
    rows = [
        ",".join(f"{v:.4f}" for v in (a, 0.1 * a, *(0.1 * a + k for k in range(7))))
        for a in t
    ]
    (tmp_path / "d.csv").write_text("\n".join([",".join(names), *rows]) + "\n")
    source = csv_source(tmp_path / "d.csv", tmp_path)
    ref = {c: ColumnRef(source=source.id, column=c) for c in names}
    project = Project(figscribe_version="test", sources=[source])
    data = LinePlot(x=ref["t"], y=ref["U"], linestyle="none", marker="o")
    fit = FitCurve(
        target=data.id, model=PredefinedFit(name="linear"), curve_range=(0.0, 15.0)
    )
    panel = Axes(x=AxisSpec(breaks=x_breaks), artists=[data])
    project.figures = [Figure(dpi=110, axes=[panel])]
    add_fit(project, fit, residuals=False).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    # Drawn after the fit: each would show what the fit had written over it.
    project.figures[0].axes[0].artists += [
        LinePlot(x=ref["t"], y=ref[name]) for name in names[2:]
    ]
    _assert_same(project, tmp_path)


def test_the_names_of_a_curve_beyond_the_data_read_plainly(tmp_path: Path) -> None:
    """On a broken axis the curve's values are a variable already, and a second
    fit uses the same names again."""
    project, ref = _scan(tmp_path)
    data = LinePlot(x=ref["t"], y=ref["U"], linestyle="none", marker="o")
    panel = Axes(x=AxisSpec(breaks=[(11.0, 12.0)]), artists=[data])
    project.figures = [Figure(dpi=110, axes=[panel])]
    for _ in range(2):
        fit = FitCurve(
            target=data.id,
            model=PredefinedFit(name="linear"),
            curve_range=(0.0, 15.0),
        )
        add_fit(project, fit, residuals=False).apply(project)
        refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "t_fit_y2" not in script and "t_fit2" not in script
    assert "t_fit_y = t_fit_y" not in script


def test_a_curve_beyond_the_data_with_residuals_sharing_x(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="data")
    fit = FitCurve(
        target=data.id, model=PredefinedFit(name="gaussian"), curve_to_limits=True
    )
    project.figures = [Figure(dpi=110, axes=[Axes(artists=[data])])]
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    project.figures[0].axes[1].x.limits = (-4.0, 14.0)  # typed below only
    script = _assert_same(project, tmp_path)
    assert "np.linspace(-4.0, 14.0, 400)" in script


def test_residuals_with_a_line_width_and_a_styled_zero_line(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="data")
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    residuals = project.figures[0].axes[1].artists[0]
    residuals.linestyle = "-"
    residuals.linewidth = 2.5
    residuals.zero_color = "tab:red"
    residuals.zero_linewidth = 1.5
    residuals.zero_linestyle = ":"
    script = _assert_same(project, tmp_path)
    assert "linewidth=2.5" in script and 'color="tab:red"' in script


def test_residuals_without_a_zero_line(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="data")
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    project.figures[0].axes[1].artists[0].zero_line = False
    script = _assert_same(project, tmp_path)
    assert "axhline" not in script


def test_notes_with_a_background_over_a_grid(tmp_path: Path) -> None:
    from figscribe.model import Annotation

    project, ref = _scan(tmp_path)
    panel = Axes(
        grid=True,
        artists=[
            LinePlot(x=ref["t"], y=ref["U"]),
            Annotation(
                text="on white",
                position=(0.4, 0.5),
                coords="axes",
                background="white",
            ),
            Annotation(
                text=r"$\mu$ here",
                position=(7.0, 0.8),
                arrow_to=(5.0, 1.0),
                color="C1",
                background="#ffeeaa",
            ),
        ],
    )
    project.figures = [Figure(dpi=100, axes=[panel])]
    script = _assert_same(project, tmp_path)
    assert script.count("bbox=") == 2 and 'facecolor="white"' in script


def _stacked_panels(ref, **figure_fields) -> Figure:
    """Two panels in a column whose tick numbers differ in width."""
    return Figure(
        dpi=100,
        layout=GridLayout(rows=2),
        axes=[
            Axes(
                y=AxisSpec(label="short", limits=(0.0, 1.0)),
                artists=[LinePlot(x=ref["t"], y=ref["U"])],
            ),
            Axes(
                row=1,
                x=AxisSpec(label="$t$", unit="s"),
                y=AxisSpec(label="long", limits=(0.0, 5000.0)),
                artists=[LinePlot(x=ref["t"], y=ref["U"])],
            ),
        ],
        **figure_fields,
    )


def test_the_labels_of_the_panels_are_aligned(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    project.figures = [_stacked_panels(ref)]
    script = _assert_same(project, tmp_path)
    assert "fig.align_labels()" in script


def test_labels_that_are_not_aligned_leave_no_call(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    project.figures = [_stacked_panels(ref, align_labels=False)]
    assert "align_labels" not in _assert_same(project, tmp_path)


def test_one_panel_has_nothing_to_align(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    figure = _stacked_panels(ref)
    figure.axes.pop()
    figure.layout = GridLayout()
    project.figures = [figure]
    assert "align_labels" not in _assert_same(project, tmp_path)


def test_panels_with_right_axes_an_inset_and_a_colour_bar_name_what_they_align(
    tmp_path: Path,
) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, Colorbar, ImagePlot, Inset

    np.save(tmp_path / "frame.npy", np.arange(60.0).reshape(6, 10))
    frame = numpy_source(tmp_path / "frame.npy", tmp_path)
    project, ref = _scan(tmp_path)
    project.sources.append(frame)
    figure = _stacked_panels(ref)
    figure.axes[0].y_right = AxisSpec(label="right", limits=(0.0, 1.0))
    figure.axes[1].artists = [
        ImagePlot(data=ArrayRef(source=frame.id), colorbar=Colorbar(label="counts"))
    ]
    figure.axes.append(
        Axes(
            inset=Inset(parent=figure.axes[0].id, bounds=(0.6, 0.6, 0.3, 0.3)),
            artists=[LinePlot(x=ref["t"], y=ref["U"])],
        )
    )
    project.figures = [figure]
    script = _assert_same(project, tmp_path)
    # Not the colour bar's axes and not the inset: just the panels and the
    # right y axis of the first.
    assert "fig.align_labels([ax_a, ax_a_right, ax_b])" in script


def test_without_the_constrained_layout_a_colour_bar_panel_is_not_aligned(
    tmp_path: Path,
) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, Colorbar, ImagePlot

    np.save(tmp_path / "frame.npy", np.arange(60.0).reshape(6, 10))
    frame = numpy_source(tmp_path / "frame.npy", tmp_path)
    project, ref = _scan(tmp_path)
    project.sources.append(frame)
    figure = _stacked_panels(ref)
    figure.axes[1].row, figure.axes[1].col = 0, 1
    figure.axes[0].y.label = "U"
    figure.axes[1].y.label = "U"
    figure.axes[1].artists = [
        ImagePlot(data=ArrayRef(source=frame.id), colorbar=Colorbar(label="counts"))
    ]
    figure.axes.append(
        Axes(
            row=1,
            y=AxisSpec(label="U", limits=(0.0, 5000.0)),
            artists=[LinePlot(x=ref["t"], y=ref["U"])],
        )
    )
    figure.layout = GridLayout(rows=2, cols=2, constrained_layout=False)
    project.figures = [figure]
    script = _assert_same(project, tmp_path)
    assert "fig.align_labels([ax_a, ax_c])" in script


def test_a_label_distance(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    figure = _stacked_panels(ref)
    figure.axes[0].y.labelpad = 12.0
    figure.axes[1].x.labelpad = 0.0
    project.figures = [figure]
    script = _assert_same(project, tmp_path)
    assert 'set_ylabel("short", labelpad=12)' in script
    assert "labelpad=0" in script


def test_a_label_distance_without_a_label_leaves_no_trace(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    figure = _stacked_panels(ref)
    figure.axes[0].x.labelpad = 12.0  # there is no x label here
    project.figures = [figure]
    assert "labelpad" not in _assert_same(project, tmp_path)


def test_a_fit_with_a_fixed_and_a_bounded_parameter(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="data")
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="gaussian"),
        initial_values={"c": 0.0},
        fixed=["c"],
        parameter_bounds={"sigma": (0.5, None)},
    )
    add_fit(project, fit).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "bounds=" in script and "c is held at 0" in script


def test_a_histogram_of_one_value(tmp_path: Path) -> None:
    """np.loadtxt gives one row of one column as a number, not an array."""
    (tmp_path / "one.csv").write_text("x,y\n1.0,2.0\n", encoding="utf-8")
    source = csv_source(tmp_path / "one.csv", tmp_path, header_row=0, skip_rows=0)
    values = ColumnRef(source=source.id, column="y")
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(dpi=72, axes=[Axes(artists=[Histogram(values=values)])])],
    )
    _assert_same(project, tmp_path)


@pytest.mark.parametrize("extend", [False, True])
def test_a_fit_over_part_of_the_data(tmp_path: Path, extend: bool) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="data")
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="gaussian"),
        fit_range=(2.5, 7.5),
        extend_curve=extend,
    )
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "in_range = (t >= 2.5) & (t <= 7.5)" in script


def test_points_left_out_of_a_plot_and_its_fit(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        label="data",
        left_out=[3, 20],
        left_out_note="more than 3σ off the Gaussian fit",
    )
    line = LinePlot(x=ref["t"], y=ref["t2"], left_out=[5, 6, 9])
    dashed = LinePlot(
        x=ref["t"],
        y=ref["U"],
        marker="o",
        left_out=[12],
        left_out_linestyle="--",
        left_out_marker=None,
    )
    points = ScatterPlot(
        x=ref["t"], y=ref["U"], left_out=[7], left_out_color="red", left_out_marker="x"
    )
    project.figures = [
        Figure(
            dpi=150,
            layout=GridLayout(rows=1, cols=2),
            axes=[
                Axes(legend=Legend(visible=True), artists=[data]),
                Axes(col=1, artists=[line, dashed, points]),
            ],
        )
    ]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "kept_1[[3, 20]] = False" in script
    assert "np.where(kept_2, t2, np.nan)" in script
    assert "more than 3σ off the Gaussian fit" in script


def test_an_errorbar_line_wider_than_its_bars(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        linestyle="--",
        linewidth=3.0,
        elinewidth=0.5,
        left_out=[4],
    )
    points = ErrorbarPlot(x=ref["t"], y=ref["t2"], yerr=ref["dU"], linewidth=3.0)
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data, points])])]
    script = _assert_same(project, tmp_path)
    # The line and its left-out steps; the points without a line have no width.
    assert script.count("linewidth=3,") == 2
    assert "elinewidth=0.5," in script


def test_points_outside_the_fit_range_drawn_like_left_out(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"], y=ref["U"], yerr=ref["dU"], linestyle="-", left_out=[18]
    )
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="gaussian"),
        fit_range=(2.5, 7.5),
        outside_as_left_out=True,
    )
    add_fit(project, fit).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "shown = kept & in_range" in script


def test_many_settings(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    left = Axes(
        col=0,
        title="Left",
        grid=True,
        x=AxisSpec(label="t", limits=(1.0, 9.0), minor_ticks=False),
        y=AxisSpec(label="U", ticks=[0.0, 0.5, 1.0], tick_labels=["0", "½", "1"]),
        legend=Legend(visible=True, position=(0.05, 0.6), frame=False, ncols=2),
        artists=[
            LinePlot(
                x=ref["t"],
                y=ref["U"],
                color="C3",
                linestyle="--",
                marker="s",
                label="line",
            ),
            ScatterPlot(
                x=ref["t"], y=ref["U"], size=8, edgecolor="k", alpha=0.5, label="pts"
            ),
            LinePlot(x=ref["t"], y=ref["dU"], visible=False),
        ],
    )
    right = Axes(
        col=1,
        x=AxisSpec(label="t", scale="log"),
        y=AxisSpec(label="$t^2$", unit="s²", scale="symlog", symlog_linthresh=1.0),
        artists=[LinePlot(x=ref["t"], y=ref["t2"], zorder=5)],
    )
    project.figures = [
        Figure(
            name="Settings",
            width_mm=175,
            height_mm=70,
            dpi=120,
            unit_format="slash",
            layout=GridLayout(cols=2, share_y="row", width_ratios=[2, 1]),
            axes=[left, right],
        )
    ]
    script = _assert_same(project, tmp_path)
    assert "sharey=ax_a" in script and "width_ratios=[2, 1]" in script


def test_decimal_comma_without_header(tmp_path: Path) -> None:
    rows = "\n".join(f"{i};{i * 0.5:.1f}".replace(".", ",") for i in range(10))
    (tmp_path / "werte.txt").write_text(f"% Messung\n{rows}\n", encoding="utf-8")
    source = csv_source(
        tmp_path / "werte.txt",
        tmp_path,
        delimiter=";",
        decimal=",",
        header_row=None,
        skip_rows=0,
        comment="%",
    )
    refs = [ColumnRef(source=source.id, column=i) for i in (0, 1)]
    project = Project(
        sources=[source],
        figures=[
            Figure(dpi=100, axes=[Axes(artists=[LinePlot(x=refs[0], y=refs[1])])])
        ],
    )
    script = _assert_same(project, tmp_path)
    assert "col0, col1 = np.loadtxt" in script and 'comments="%"' in script


def test_a_style_sheet_and_whitespace_columns(tmp_path: Path) -> None:
    rows = "\n".join(f"{i}  {i**2}  {i % 3}" for i in range(12))
    (tmp_path / "plain.dat").write_text(f"x y z\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "plain.dat", tmp_path, delimiter=None)
    ref = {c: ColumnRef(source=source.id, column=c) for c in ("y", "z")}
    project = Project(
        sources=[source],
        figures=[
            Figure(
                dpi=100,
                stylesheet="seaborn-v0_8-talk",
                axes=[Axes(artists=[ScatterPlot(x=ref["z"], y=ref["y"])])],
            )
        ],
    )
    script = _assert_same(project, tmp_path)
    assert "usecols=(2, 1)" in script and 'plt.style.use("seaborn-v0_8-talk")' in script


def test_panels_added_beside_and_inside(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    first = Axes(artists=[LinePlot(x=ref["t"], y=ref["U"])])
    project.figures = [Figure(dpi=100, width_mm=120, axes=[first])]
    for side in ("right", "right", "below", "inset"):
        add_panel(project, first.id, side)[0].apply(project)
    inset = project.figures[0].axes[-1]
    inset.artists.append(ScatterPlot(x=ref["t"], y=ref["dU"]))
    script = _assert_same(project, tmp_path)
    assert "ax_e = ax_a.inset_axes([0.55, 0.55, 0.4, 0.4])" in script


def test_font_sizes_ticks_and_grid(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        title="Sizes",
        title_size=14,
        grid=True,
        grid_axis="y",
        grid_which="both",
        x=AxisSpec(label="t", label_size=12, major_step=2.5, minor_divisions=5),
        y=AxisSpec(label="U", tick_size=6, ticks=[0, 1], major_step=0.1),
        artists=[LinePlot(x=ref["t"], y=ref["U"], label="U")],
        legend=Legend(visible=True),
    )
    project.figures = [Figure(dpi=110, font_size=7, axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert 'plt.rcParams["font.size"] = 7' in script
    assert "ax.xaxis.set_major_locator(MultipleLocator(2.5))" in script
    assert "ax.xaxis.set_minor_locator(AutoMinorLocator(5))" in script
    assert "MultipleLocator(0.1)" not in script  # explicit ticks win
    assert 'ax.grid(True, which="major", axis="y")' in script
    assert 'ax.grid(True, which="minor", axis="y", linewidth=' in script


def test_a_tick_step_too_small_is_left_to_matplotlib(tmp_path: Path) -> None:
    # The renderer falls back to automatic ticks; the script must do the same,
    # for a fixed range and for one that follows the data.
    project, ref = _scan(tmp_path)
    axes = Axes(
        x=AxisSpec(limits=(0, 10_000), major_step=1),
        y=AxisSpec(major_step=0.0001),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [Figure(dpi=100, axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert "MultipleLocator" not in script


def test_font_size_with_a_style_sheet(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(x=AxisSpec(label="t"), artists=[ScatterPlot(x=ref["t"], y=ref["U"])])
    project.figures = [
        Figure(dpi=100, stylesheet="seaborn-v0_8-talk", font_size=9, axes=[axes])
    ]
    _assert_same(project, tmp_path)


def test_a_windows_file_keeps_its_encoding(tmp_path: Path) -> None:
    text = "t;I (µA)\n0;1,5\n1;2,5\n2;2\n"
    (tmp_path / "old.csv").write_bytes(text.encode("cp1252"))
    source = csv_source(
        tmp_path / "old.csv", tmp_path, delimiter=";", decimal=",", encoding="cp1252"
    )
    ref = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    axes = Axes(artists=[LinePlot(x=ref["t"], y=ref["I (µA)"])])
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(dpi=100, axes=[axes])],
    )
    script = _assert_same(project, tmp_path)
    assert 'encoding="cp1252"' in script


@pytest.mark.parametrize(
    ("header", "bom", "expected"),
    [
        ("t,U (V)", False, None),
        ("t,I (µA)", False, '"utf-8"'),
        ("t,I (µA)", True, '"utf-8-sig"'),
    ],
)
def test_a_utf8_file_names_its_encoding_unless_plain_ascii(
    tmp_path: Path, header: str, bom: bool, expected: str | None
) -> None:
    """Without encoding=, NumPy reads with the system's encoding: cp1252 on
    Windows, which cannot decode every UTF-8 byte (0x81 in "Á")."""
    text = f"{header}\n0,1.5\n1,2.5\n2,2\n"
    (tmp_path / "data.csv").write_bytes(
        ("\ufeff" if bom else "").encode() + text.encode()
    )
    source = csv_source(tmp_path / "data.csv", tmp_path)
    ref = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    y = next(c for c in source.columns if c != "t")
    axes = Axes(artists=[LinePlot(x=ref["t"], y=ref[y])])
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(dpi=100, axes=[axes])],
    )
    script = _assert_same(project, tmp_path)
    if expected is None:
        assert "encoding=" not in script
    else:
        assert f"encoding={expected}" in script


def test_histograms_and_notes(tmp_path: Path) -> None:
    from figscribe.model import Annotation, Histogram

    project, ref = _scan(tmp_path)
    left = Axes(
        col=0,
        legend=Legend(visible=True),
        artists=[
            Histogram(values=ref["U"], bins=12, label="U"),
            Histogram(
                values=ref["t"],
                bins=[0.0, 2.5, 5.0, 10.0],
                density=True,
                histtype="step",
                color="C3",
                label="t",
            ),
            Annotation(text="counts", position=(0.05, 0.9), coords="axes"),
            Annotation(
                text="$y = a x + b$\nwith $\\mu$ fitted",
                position=(0.05, 0.6),
                coords="axes",
            ),
        ],
    )
    right = Axes(
        col=1,
        artists=[
            LinePlot(x=ref["t"], y=ref["U"]),
            Annotation(
                text=r"$\mu$",
                position=(7.0, 0.8),
                arrow_to=(5.0, 1.0),
                fontsize=12,
                color="C1",
            ),
            Annotation(
                text="corner",
                position=(0.7, 0.1),
                coords="axes",
                arrow_to=(0.9, 0.3),
                zorder=4,
            ),
        ],
    )
    project.figures = [
        Figure(dpi=100, width_mm=150, layout=GridLayout(cols=2), axes=[left, right])
    ]
    script = _assert_same(project, tmp_path)
    assert "bins=[0, 2.5, 5, 10]" in script and 'histtype="step"' in script
    assert 'arrowprops=dict(arrowstyle="->", color="C1")' in script


def test_a_histogram_of_values_with_gaps(tmp_path: Path) -> None:
    from figscribe.model import Histogram

    rows = "\n".join(["1.0", "nan", "2.5", "2.0", "inf", "3.5", "2.2"])
    (tmp_path / "gaps.csv").write_text(f"v\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "gaps.csv", tmp_path)
    values = ColumnRef(source=source.id, column="v")
    project = Project(
        sources=[source],
        figures=[
            Figure(dpi=100, axes=[Axes(artists=[Histogram(values=values, bins=4)])])
        ],
    )
    script = _assert_same(project, tmp_path)
    assert "ax.hist(v[np.isfinite(v)], bins=4" in script


def test_a_right_y_axis(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        x=AxisSpec(label="t", unit="s"),
        y=AxisSpec(label="U", unit="V"),
        y_right=AxisSpec(label="$t^2$", unit="s²", scale="log", tick_size=7),
        legend=Legend(visible=True, location="upper left"),
        artists=[
            ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"], label="U"),
            LinePlot(x=ref["t"], y=ref["t2"], axis="right", color="C1", label="t²"),
            ScatterPlot(x=ref["t"], y=ref["t2"], axis="right", size=6),
        ],
    )
    other = Axes(row=1, artists=[LinePlot(x=ref["t"], y=ref["U"])])
    project.figures = [
        Figure(
            dpi=100,
            height_mm=90,
            layout=GridLayout(rows=2, share_x="col"),
            axes=[axes, other],
        )
    ]
    script = _assert_same(project, tmp_path)
    assert "ax_a_right = ax_a.twinx()" in script
    assert "ax_a.legend(handles + right_handles, labels + right_labels" in script


def test_images_meshes_and_colour_bars(tmp_path: Path) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, Colorbar, ColorMesh, ImagePlot

    yy, xx = np.mgrid[0:20, 0:30]
    matrix = np.exp(-((xx - 12.0) ** 2 + (yy - 8.0) ** 2) / 40.0) + 0.01
    rows = "\n".join(";".join(f"{v:.6f}" for v in row) for row in matrix)
    (tmp_path / "map.csv").write_text(rows + "\n", encoding="utf-8")
    table = csv_source(tmp_path / "map.csv", tmp_path, delimiter=";", header_row=None)
    np.save(tmp_path / "frame.npy", (matrix * 100).astype(int))
    frame = numpy_source(tmp_path / "frame.npy", tmp_path)
    np.savez(
        tmp_path / "scan.npz",
        counts=matrix[:5, :6],
        x=np.arange(6.0) * 0.5,
        y=np.array([0.0, 1.0, 1.5, 3.0, 4.0]),
    )
    mesh_source = numpy_source(tmp_path / "scan.npz", tmp_path, array="x")
    y_source = numpy_source(tmp_path / "scan.npz", tmp_path, array="y")

    image = ImagePlot(
        data=ArrayRef(source=table.id),
        cmap="magma",
        norm="log",
        vmin=0.01,
        origin="lower",
        extent=(0.0, 3.0, 0.0, 2.0),
        colorbar=Colorbar(label="intensity"),
    )
    raw = ImagePlot(data=ArrayRef(source=frame.id), aspect="equal", vmax=80.0)
    mesh = ColorMesh(
        c=ArrayRef(source=mesh_source.id, key="counts"),
        x=ColumnRef(source=mesh_source.id, column=0),
        y=ColumnRef(source=y_source.id, column=0),
        cmap="cividis",
        colorbar=Colorbar(),
    )
    project = Project(
        sources=[table, frame, mesh_source, y_source],
        figures=[
            Figure(
                dpi=100,
                width_mm=175,
                layout=GridLayout(cols=3),
                axes=[
                    Axes(col=0, artists=[image]),
                    Axes(col=1, artists=[raw]),
                    Axes(col=2, artists=[mesh]),
                ],
            )
        ],
    )
    script = _assert_same(project, tmp_path)
    assert "map_table = np.loadtxt(map_path" in script
    assert 'scan_counts = np.load(scan_path)["counts"].astype(float)' in script
    assert 'fig.colorbar(image, ax=ax_a, label="intensity")' in script
    assert "norm=LogNorm(vmin=0.01)" in script


def test_a_mesh_with_cell_positions_along_x_only(tmp_path: Path) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, ColorMesh

    yy, xx = np.mgrid[0:5, 0:6]
    np.savez(tmp_path / "scan.npz", counts=xx * yy + 1.0, x=np.arange(6.0) ** 1.5)
    counts = numpy_source(tmp_path / "scan.npz", tmp_path, array="counts")
    x_source = numpy_source(tmp_path / "scan.npz", tmp_path, array="x")
    mesh = ColorMesh(
        c=ArrayRef(source=counts.id), x=ColumnRef(source=x_source.id, column=0)
    )
    project = Project(
        sources=[counts, x_source],
        figures=[Figure(dpi=100, axes=[Axes(artists=[mesh])])],
    )
    script = _assert_same(project, tmp_path)
    assert ".shape[0])" in script  # the rows numbered, as the panel says


def test_allan_deviations_of_frequency_and_phase(tmp_path: Path) -> None:
    from figscribe.model import AllanDeviationPlot

    rng = np.random.default_rng(7)
    y = rng.normal(scale=2e-12, size=300) + np.linspace(0.0, 1e-12, 300)
    x = np.concatenate([[0.0], np.cumsum(y) * 0.5])[:-1]
    gap = y.copy()
    gap[40] = np.nan
    rows = [
        f"{0.5 * i!r},{float(a)!r},{float(b)!r},{float(c)!r}"
        for i, (a, b, c) in enumerate(zip(y, x, gap, strict=True))
    ]
    (tmp_path / "clock.csv").write_text(
        "t,y,x,gap\n" + "\n".join(rows) + "\n", encoding="utf-8"
    )
    source = csv_source(tmp_path / "clock.csv", tmp_path, header_row=0)

    def col(name: str) -> ColumnRef:
        return ColumnRef(source=source.id, column=name)

    log = {"x": AxisSpec(scale="log"), "y": AxisSpec(scale="log")}
    plots = [
        AllanDeviationPlot(values=col("y"), sample_interval=0.5, label="frequency"),
        AllanDeviationPlot(
            values=col("x"),
            data_type="phase",
            time=col("t"),
            taus="decade",
            error_bars=False,
            marker="s",
            linestyle="--",
            label="phase",
        ),
        AllanDeviationPlot(values=col("gap"), label="with a gap"),
    ]
    project = Project(
        sources=[source],
        figures=[
            Figure(
                dpi=120,
                axes=[Axes(legend=Legend(visible=True), artists=plots, **log)],
            )
        ],
    )
    script = _assert_same(project, tmp_path)
    assert "def overlapping_adev(phase, tau0, m):" in script
    assert "tau0_2 = np.median(np.diff(t))" in script
    assert "has gaps, so its Allan deviation is not drawn" in script
    assert "allantools" not in script


def test_ticks_inside_on_all_sides_with_prefixes(tmp_path: Path) -> None:
    """A spectrum as journals print it: kHz on x, a stepped y range with four
    minor ticks, ticks inside on all four sides; the right axis and an inset
    get the same tick style."""
    project, ref = _scan(tmp_path)
    spectrum = Axes(
        x=AxisSpec(label="t", unit="s", prefix="m", major_step=2.5),
        y=AxisSpec(
            label="U", unit="V", limits=(0, 1.2), major_step=0.4, minor_divisions=5
        ),
        y_right=AxisSpec(label="P", prefix="k"),
        artists=[
            LinePlot(x=ref["t"], y=ref["U"]),
            ScatterPlot(x=ref["t"], y=ref["dU"], axis="right"),
        ],
    )
    project.figures = [
        Figure(dpi=110, tick_direction="in", ticks_all_sides=True, axes=[spectrum])
    ]
    script = _assert_same(project, tmp_path)
    assert '"xtick.direction": "in"' in script and '"ytick.right": True' in script
    assert 'f"{(v if abs(v) > 2.5e-06 else 0) * 1e3:g}"' in script
    assert 'f"{v / 1e3:g}"' in script
    assert '"t (ms)"' in script


def test_a_prefixed_axis_with_negative_ticks_and_a_step(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        x=AxisSpec(label="t", prefix="m", limits=(-0.0533, 0.0533), major_step=0.01),
        y=AxisSpec(label="U", prefix="m", limits=(-1.2, 1.2)),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [Figure(dpi=110, width_mm=175, axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert "abs(v) > 1e-08 else 0" in script
    assert "FuncFormatter.fix_minus" in script


def test_number_formats_with_a_decimal_comma(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    panel = Axes(
        x=AxisSpec(
            label="t",
            number_format="fixed",
            decimals=2,
            limits=(-0.0533, 0.0533),
            major_step=0.02,
        ),
        y=AxisSpec(
            label="U",
            prefix="m",
            number_format="scientific",
            limits=(-1.2, 1.2),
            major_step=0.4,
        ),
        y_right=AxisSpec(label="P", prefix="k"),
        artists=[
            LinePlot(x=ref["t"], y=ref["U"]),
            ScatterPlot(x=ref["t"], y=ref["dU"], axis="right"),
        ],
    )
    project.figures = [Figure(dpi=110, width_mm=175, decimal_comma=True, axes=[panel])]
    script = _assert_same(project, tmp_path)
    assert "def decimal_comma(text):" in script
    assert "def power_of_ten(value, decimals):" in script
    assert 'f"{round(v, 2) + 0:.2f}"' in script
    assert ":z." not in script  # needs Python 3.11, which the script must not
    assert "CommaFormatter" not in script  # no axis keeps Matplotlib's numbers


@pytest.mark.parametrize("number_format", ["fixed", "scientific"])
def test_a_number_format_with_the_point(tmp_path: Path, number_format) -> None:
    project, ref = _scan(tmp_path)
    panel = Axes(
        x=AxisSpec(label="t", number_format=number_format, limits=(-5, 5)),
        y=AxisSpec(label="U", scale="log", number_format=number_format),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [Figure(dpi=110, width_mm=175, axes=[panel])]
    script = _assert_same(project, tmp_path)
    assert "decimal_comma" not in script
    assert ("power_of_ten" in script) == (number_format == "scientific")


def test_matplotlibs_own_numbers_with_a_decimal_comma(tmp_path: Path) -> None:
    """An offset at the end of an axis, minor numbers on a log axis spanning
    less than a decade, a symmetric log axis, an inset and typed labels."""
    from figscribe.model import Inset

    project, ref = _scan(tmp_path)
    first = Axes(
        x=AxisSpec(label="t", limits=(1000.15, 1000.55)),
        y=AxisSpec(label="U", scale="log", limits=(0.2, 0.75)),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    second = Axes(
        col=1,
        x=AxisSpec(
            label="t", scale="symlog", symlog_linthresh=0.5, ticks=[0, 0.5, 2.5]
        ),
        y=AxisSpec(label="U", ticks=[0.25, 0.75], tick_labels=["0.25 V", "max."]),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    inset = Axes(
        inset=Inset(parent=second.id), artists=[LinePlot(x=ref["t"], y=ref["dU"])]
    )
    project.figures = [
        Figure(
            dpi=110,
            width_mm=175,
            decimal_comma=True,
            layout=GridLayout(cols=2),
            axes=[first, second, inset],
        )
    ]
    script = _assert_same(project, tmp_path)
    assert "class CommaFormatter(ScalarFormatter):" in script
    assert "class CommaLogFormatter(LogFormatterSciNotation):" in script
    assert "set_minor_formatter(CommaLogFormatter())" in script
    assert '"0.25 V"' in script


@pytest.mark.parametrize("norm", ["linear", "log"])
@pytest.mark.parametrize("top", [4.5, 4000.0])
def test_a_color_bar_with_a_decimal_comma(tmp_path: Path, norm, top) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, Colorbar, ColorMesh

    z = np.linspace(2.0, top, 20).reshape(4, 5)
    np.save(tmp_path / "z.npy", z)
    source = numpy_source(tmp_path / "z.npy", tmp_path)
    mesh = ColorMesh(
        c=ArrayRef(source=source.id), norm=norm, colorbar=Colorbar(label="I")
    )
    project = Project(
        sources=[source],
        figures=[Figure(dpi=110, decimal_comma=True, axes=[Axes(artists=[mesh])])],
    )
    _assert_same(project, tmp_path)


@pytest.mark.parametrize("formatted", [0, 1])
def test_shared_axes_with_different_number_formats(tmp_path: Path, formatted) -> None:
    """Panels that share an axis share its formatter: the script must end up
    with the same one as the renderer."""
    project, ref = _scan(tmp_path)
    specs = [AxisSpec(), AxisSpec()]
    specs[formatted] = AxisSpec(number_format="fixed", decimals=3)
    project.figures = [
        Figure(
            dpi=110,
            decimal_comma=True,
            layout=GridLayout(rows=2, share_x="col"),
            axes=[
                Axes(row=i, x=specs[i], artists=[LinePlot(x=ref["t"], y=ref["U"])])
                for i in range(2)
            ],
        )
    ]
    _assert_same(project, tmp_path)


@pytest.mark.parametrize("comma", [False, True])
@pytest.mark.parametrize("formatted", [0, 1])
def test_shared_log_axes_with_different_number_formats(
    tmp_path: Path, formatted, comma
) -> None:
    """Setting a shared log scale again resets its formatters; the script must
    not do that after it has set them."""
    project, ref = _scan(tmp_path)
    specs = [AxisSpec(scale="log"), AxisSpec(scale="log")]
    specs[formatted] = AxisSpec(scale="log", number_format="fixed", major_step=2)
    project.figures = [
        Figure(
            dpi=110,
            decimal_comma=comma,
            layout=GridLayout(rows=2, share_x="col"),
            axes=[
                Axes(row=i, x=specs[i], artists=[LinePlot(x=ref["t"], y=ref["U"])])
                for i in range(2)
            ],
        )
    ]
    _assert_same(project, tmp_path)


@pytest.mark.parametrize("comma", [False, True])
@pytest.mark.parametrize("typed_on", [0, 1])
def test_typed_labels_on_a_shared_axis(tmp_path: Path, typed_on, comma) -> None:
    project, ref = _scan(tmp_path)
    specs = [AxisSpec(), AxisSpec()]
    specs[typed_on] = AxisSpec(ticks=[1, 3], tick_labels=["one", "three"])
    project.figures = [
        Figure(
            dpi=110,
            decimal_comma=comma,
            layout=GridLayout(rows=2, share_x="col"),
            axes=[
                Axes(row=i, x=specs[i], artists=[LinePlot(x=ref["t"], y=ref["U"])])
                for i in range(2)
            ],
        )
    ]
    _assert_same(project, tmp_path)


@pytest.mark.parametrize(
    ("spec", "comma"),
    [
        (AxisSpec(scale="log", prefix="k", limits=(0.2, 0.8)), False),
        (AxisSpec(scale="log", limits=(0.2, 0.8)), True),
        (AxisSpec(scale="log", limits=(0.2, 0.8)), False),
        (AxisSpec(scale="symlog", limits=(-3, 30)), True),
    ],
    ids=["prefix", "comma", "plain", "symlog"],
)
def test_a_log_axis_without_minor_ticks(tmp_path: Path, spec, comma) -> None:
    project, ref = _scan(tmp_path)
    x = spec.model_copy(update={"minor_ticks": False})
    project.figures = [
        Figure(
            dpi=110,
            decimal_comma=comma,
            axes=[Axes(x=x, artists=[LinePlot(x=ref["t"], y=ref["U"])])],
        )
    ]
    _assert_same(project, tmp_path)


def test_the_longest_tick_formatter_stays_within_the_width(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    spec = AxisSpec(prefix="m", major_step=0.00001, limits=(-0.00003, 0.00003))
    panel = Axes(x=spec, y=spec, artists=[LinePlot(x=ref["t"], y=ref["U"])])
    panel.y_right = spec
    project.figures = [Figure(dpi=110, width_mm=175, decimal_comma=True, axes=[panel])]
    script = _assert_same(project, tmp_path)
    assert [line for line in script.splitlines() if len(line) > 88] == []


def test_columns_named_like_the_tick_helpers(tmp_path: Path) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, Colorbar, ColorMesh

    names = [
        "decimal_comma",
        "power_of_ten",
        "CommaFormatter",
        "CommaLogFormatter",
        "MinorLogNumbers",
        "colorbar",
    ]
    rows = "\n".join(",".join(str(i + k) for k in range(6)) for i in range(1, 6))
    (tmp_path / "t.csv").write_text(
        ",".join(names) + "\n" + rows + "\n", encoding="utf-8"
    )
    table = csv_source(tmp_path / "t.csv", tmp_path)
    np.save(tmp_path / "z.npy", np.arange(1.0, 21.0).reshape(4, 5))
    frame = numpy_source(tmp_path / "z.npy", tmp_path)

    def ref(name: str) -> ColumnRef:
        return ColumnRef(source=table.id, column=name)

    plots = Axes(
        x=AxisSpec(number_format="scientific"),
        y=AxisSpec(scale="log", prefix="m"),
        artists=[
            LinePlot(x=ref(names[i]), y=ref(names[i + 1])) for i in range(0, 6, 2)
        ],
    )
    mesh = Axes(
        col=1,
        x=AxisSpec(scale="log", limits=(1, 5)),
        artists=[
            ColorMesh(c=ArrayRef(source=frame.id), norm="log", colorbar=Colorbar())
        ],
    )
    project = Project(
        sources=[table, frame],
        figures=[
            Figure(
                dpi=110,
                width_mm=175,
                decimal_comma=True,
                layout=GridLayout(cols=2),
                axes=[plots, mesh],
            )
        ],
    )
    _assert_same(project, tmp_path)


@pytest.mark.parametrize("comma", [False, True])
def test_log_axes_of_less_than_a_decade_with_numbers_of_our_own(
    tmp_path: Path, comma
) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        x=AxisSpec(label="t", scale="log", prefix="m", limits=(0.2, 0.8)),
        y=AxisSpec(
            label="U",
            scale="log",
            number_format="scientific",
            limits=(0.15, 0.9),
        ),
        y_right=AxisSpec(scale="log", number_format="fixed", limits=(0.002, 5.0)),
        artists=[
            LinePlot(x=ref["t"], y=ref["U"]),
            ScatterPlot(x=ref["t"], y=ref["dU"], axis="right"),
        ],
    )
    project.figures = [Figure(dpi=110, width_mm=175, decimal_comma=comma, axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert "class MinorLogNumbers(LogFormatterSciNotation):" in script
    assert "NullFormatter" not in script


def test_a_stepped_log_axis_keeps_its_minor_ticks(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        x=AxisSpec(
            label="t",
            scale="log",
            limits=(1.3, 1.4),
            major_step=0.05,
            minor_divisions=5,
        ),
        y=AxisSpec(label="U", scale="log", prefix="m"),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [Figure(dpi=110, tick_direction="inout", axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert "MultipleLocator(0.01)" in script  # 0.05 in five parts
    assert "AutoMinorLocator" not in script
    assert "NullFormatter()" in script


@pytest.mark.parametrize(
    ("grid", "written"),
    [
        (
            {"grid_which": "both"},
            'linewidth=plt.rcParams["grid.linewidth"] / 2',
        ),
        (
            {"grid_which": "both", "grid_linewidth": 1.4, "grid_axis": "y"},
            'ax.grid(True, which="minor", axis="y", linewidth=0.7)',
        ),
        (
            {
                "grid_which": "both",
                "grid_color": "dimgray",
                "grid_minor_color": "silver",
                "grid_minor_linestyle": ":",
                "grid_minor_linewidth": 0.3,
            },
            'which="minor"',
        ),
        (
            {"grid_which": "minor", "grid_minor_linewidth": 0.3},
            'ax.grid(True, which="minor", linewidth=0.3)',
        ),
    ],
    ids=["default", "half-the-major", "own", "minor-alone"],
)
def test_minor_grid_lines(tmp_path: Path, grid, written) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(grid=True, artists=[LinePlot(x=ref["t"], y=ref["U"])], **grid)
    project.figures = [Figure(dpi=110, axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert written in script
    assert [line for line in script.splitlines() if len(line) > 88] == []


def test_minor_grid_lines_on_broken_axes(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        grid=True,
        grid_which="both",
        x=AxisSpec(breaks=[(4.2, 5.8)]),
        y=AxisSpec(breaks=[(0.4, 0.6)]),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [Figure(dpi=110, axes=[axes])]
    _assert_same(project, tmp_path)


def test_a_grid_in_its_own_color(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        x=AxisSpec(label="t"),
        grid=True,
        grid_color="dimgray",
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [Figure(dpi=110, axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert 'ax.grid(True, color="dimgray")' in script


def test_wide_frame_long_ticks_and_a_dotted_grid(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        grid=True,
        grid_which="both",
        grid_linewidth=0.4,
        grid_linestyle=":",
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [
        Figure(
            dpi=110,
            frame_width=1.5,
            tick_width=1.2,
            tick_length=6.0,
            minor_tick_width=0.8,
            minor_tick_length=3.0,
            axes=[axes],
        )
    ]
    script = _assert_same(project, tmp_path)
    assert '"axes.linewidth": 1.5' in script
    assert '"xtick.major.size": 6' in script and '"ytick.minor.width": 0.8' in script
    assert 'ax.grid(True, which="major", linewidth=0.4, linestyle=":")' in script
    assert 'ax.grid(True, which="minor", linewidth=0.2, linestyle=":")' in script


def test_panel_labels_outside_with_an_inset_lettered(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    first = Axes(
        x=AxisSpec(label="$t$", unit="s"),
        y=AxisSpec(label="$U$", unit="V"),
        artists=[LinePlot(x=ref["t"], y=ref["U"])],
    )
    project.figures = [
        Figure(
            dpi=100,
            width_mm=120,
            axes=[first],
            panel_labels=PanelLabels(style="a)", bold=True, insets=True),
        )
    ]
    for side in ("right", "below", "inset"):
        add_panel(project, first.id, side)[0].apply(project)
    script = _assert_same(project, tmp_path)
    assert (
        'for ax, label in [(ax_a, "a)"), (ax_d, "b)"), (ax_b, "c)"), (ax_c, "d)")]:'
        in script
    )
    assert 'textcoords="offset fontsize"' in script
    assert 'fontweight="bold"' in script


def test_a_panel_label_inside_one_panel(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    project.figures = [
        Figure(
            dpi=100,
            axes=[Axes(artists=[LinePlot(x=ref["t"], y=ref["U"])])],
            panel_labels=PanelLabels(style="A", placement="inside", fontsize=13),
        )
    ]
    script = _assert_same(project, tmp_path)
    assert "ax.annotate(\n" in script and '"A",' in script
    assert "fontsize=13" in script and "for ax, label" not in script


def test_reference_lines_and_shaded_spans(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    axes = Axes(
        x=AxisSpec(label="$t$", unit="s"),
        y=AxisSpec(label="$U$", unit="V", scale="log", limits=(0.01, 2)),
        y_right=AxisSpec(label="$t^2$", unit="s2"),
        legend=Legend(visible=True),
        artists=[
            LinePlot(x=ref["t"], y=ref["U"], label="data"),
            ScatterPlot(x=ref["t"], y=ref["t2"], axis="right"),
            ReferenceLine(at=5.0, label="centre"),
            ReferenceLine(
                orientation="horizontal",
                at=60.0,
                axis="right",
                color="C3",
                linestyle="-.",
                linewidth=2.0,
            ),
            ShadedSpan(start=3.5, end=6.5, label="peak", zorder=3.0),
            ShadedSpan(orientation="horizontal", start=0.5, end=1.0, color="C2"),
        ],
    )
    project.figures = [Figure(dpi=100, width_mm=110, axes=[axes])]
    script = _assert_same(project, tmp_path)
    assert (
        'ax.axvline(5, color="gray", linestyle="--", linewidth=1, label="centre")'
        in (script)
    )
    assert "ax_right.axhline(60," in script
    assert (
        'ax.axvspan(3.5, 6.5, color="gray", linewidth=0, label="peak", zorder=3, '
        "alpha=0.2)" in script
    )
    assert 'ax.axhspan(0.5, 1, color="C2", linewidth=0, zorder=0.5, alpha=0.2)' in (
        script
    )


def test_error_bands(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        linestyle="-",
        marker="none",
        label="data",
        left_out=[12],
        band=ErrorBand(),
    )
    shifted = ErrorbarPlot(
        x=ref["t"],
        y=ref["t2"],
        xerr=ref["dU"],
        yerr=ref["U"],
        color="C3",
        alpha=0.8,
        zorder=2.3,
        band=ErrorBand(color="0.6", alpha=0.5),
    )
    project.figures = [
        Figure(
            dpi=150,
            layout=GridLayout(cols=2),
            axes=[
                Axes(legend=Legend(visible=True), artists=[data]),
                Axes(col=1, artists=[shifted]),
            ],
        )
    ]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "line, = ax_a.plot(" in script
    assert "    where=kept,\n    color=line.get_color(),\n    alpha=0.25,\n" in script
    assert "line, _, _ =" not in script  # the second plot has a color of its own
    assert (
        'ax_b.fill_between(t, t2 - U, t2 + U, color="0.6", alpha=0.4, zorder=2.2, '
        "linewidth=0)" in script
    )


def test_an_error_band_beside_x_error_bars_in_the_cycle_color(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"], y=ref["U"], xerr=ref["dU"], yerr=ref["dU"], band=ErrorBand()
    )
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    script = _assert_same(project, tmp_path)
    assert "line, _, _ = ax.errorbar(" in script
    assert "color=line.get_color()" in script


def _run_csv(folder: Path) -> tuple[Project, dict[str, ColumnRef]]:
    """A measurement with timestamps in s, every 6 min for 4 h."""
    t = 1.7e9 + 360.0 * np.arange(41)
    rng = np.random.default_rng(5)
    u = np.exp(-(((t - t[20]) / 3600) ** 2)) + rng.normal(0, 0.03, t.size)
    rows = "\n".join(f"{float(a)!r},{b:.5f},0.030" for a, b in zip(t, u, strict=True))
    (folder / "run.csv").write_text(f"t,U,dU\n{rows}\n", encoding="utf-8")
    source = csv_source(folder / "run.csv", folder, header_row=0)
    refs = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    return Project(figscribe_version="test", sources=[source]), refs


def test_units_and_a_range_with_a_band_and_a_fit(tmp_path: Path) -> None:
    from figscribe.model import Conversion, ErrorBand

    project, ref = _run_csv(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        label="data",
        linestyle="-",
        band=ErrorBand(),
        x_conversion=Conversion(factor=1 / 3600, from_start=True, unit="h"),
        y_conversion=Conversion(factor=1000.0, unit="mV"),
        x_range=(0.5, 3.5),
        left_out=[2, 30],  # row 2 lies outside the range
    )
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    assert project.figures[0].axes[0].artists[1].result.parameters["mu"] == (
        pytest.approx(2.0, abs=0.05)  # in h, as the axis shows it
    )
    script = _assert_same(project, tmp_path)
    assert "t_h = (t - np.nanmin(t)) / 3600  # h since the start" in script
    assert "U_mV = U * 1000  # in mV" in script
    assert "dU_mV = dU * 1000" in script
    assert "used = (t_h >= 0.5) & (t_h <= 3.5)" in script


def test_a_histogram_over_a_range(tmp_path: Path) -> None:
    from figscribe.model import Conversion, Histogram

    project, ref = _run_csv(tmp_path)
    counts = Histogram(
        values=ref["U"],
        bins=8,
        x_conversion=Conversion(factor=1000.0, unit="mV"),
        x_range=(100.0, 900.0),
    )
    project.figures = [Figure(dpi=100, axes=[Axes(artists=[counts])])]
    script = _assert_same(project, tmp_path)
    assert "range=(100, 900)" in script


def test_an_allan_deviation_in_minutes_over_a_range(tmp_path: Path) -> None:
    from figscribe.model import AllanDeviationPlot, Conversion

    rng = np.random.default_rng(11)
    y = rng.normal(scale=2e-12, size=400)
    rows = "\n".join(f"{0.5 * i!r},{float(v)!r}" for i, v in enumerate(y))
    (tmp_path / "clock.csv").write_text(f"t,y\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "clock.csv", tmp_path, header_row=0)
    col = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    minutes = Conversion(factor=1 / 60, unit="min")
    plots = [
        AllanDeviationPlot(
            values=col["y"], time=col["t"], x_conversion=minutes, x_range=(0.0, 1.5)
        ),
        AllanDeviationPlot(
            values=col["y"], sample_interval=0.5, x_conversion=minutes, x_range=(1, 3)
        ),
    ]
    log = {"x": AxisSpec(scale="log"), "y": AxisSpec(scale="log")}
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(dpi=100, axes=[Axes(**log, artists=plots)])],
    )
    script = _assert_same(project, tmp_path)
    assert "/ 60" in script


@pytest.mark.parametrize(
    "case",
    ["plain", "minutes and a range", "fit range", "no error bars", "linear axes"],
)
def test_a_fit_of_an_allan_deviation_with_its_residuals(
    tmp_path: Path, case: str
) -> None:
    """F14, decision 0064: the fit runs on the points the plot draws, and the
    script on the variables that hold them."""
    from figscribe.model import AllanDeviationPlot, Conversion, ExpressionFit

    rng = np.random.default_rng(5)
    y = rng.normal(scale=2e-12, size=600)
    rows = "\n".join(f"{0.5 * i!r},{float(v)!r}" for i, v in enumerate(y))
    (tmp_path / "clock.csv").write_text(f"t,y\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "clock.csv", tmp_path, header_row=0)
    col = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    plot = AllanDeviationPlot(values=col["y"], time=col["t"])
    fit_range = None
    if case == "minutes and a range":
        plot.x_conversion = Conversion(factor=1 / 60, unit="min")
        plot.x_range = (0.0, 4.0)
    if case == "fit range":
        fit_range = (1.5, 60.0)
    if case == "no error bars":
        plot.error_bars = False
    log = {"x": AxisSpec(scale="log"), "y": AxisSpec(scale="log")}
    axes = Axes(**({} if case == "linear axes" else log), artists=[plot])
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(dpi=100, axes=[axes])],
    )
    fit = FitCurve(
        target=plot.id,
        model=ExpressionFit(expression="a / sqrt(x)", parameters=["a"]),
        initial_values={"a": 1e-12},
        fit_range=fit_range,
    )
    add_fit(project, fit, residuals=True).apply(project)
    placed = next(a for a in project.figures[0].axes[0].artists if a.id == fit.id)
    refit(project, placed.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "curve_fit(" in script and "import figscribe" not in script
    if case != "linear axes":
        assert "geomspace" in script  # even along a logarithmic τ axis


def test_an_allan_fit_stays_equal_after_the_error_bars_are_switched_off(
    tmp_path: Path,
) -> None:
    from figscribe.model import AllanDeviationPlot, ExpressionFit
    from figscribe.units import set_allan_field

    rng = np.random.default_rng(6)
    y = rng.normal(scale=2e-12, size=600)
    rows = "\n".join(f"{0.5 * i!r},{float(v)!r}" for i, v in enumerate(y))
    (tmp_path / "clock.csv").write_text(f"t,y\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "clock.csv", tmp_path, header_row=0)
    col = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    plot = AllanDeviationPlot(values=col["y"], time=col["t"])
    log = {"x": AxisSpec(scale="log"), "y": AxisSpec(scale="log")}
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(dpi=100, axes=[Axes(**log, artists=[plot])])],
    )
    fit = FitCurve(
        target=plot.id,
        model=ExpressionFit(expression="a / sqrt(x)", parameters=["a"]),
        initial_values={"a": 1e-12},
    )
    add_fit(project, fit, residuals=True).apply(project)
    data = load_data(project, tmp_path)
    refit(project, fit.id, data).apply(project)
    set_allan_field(
        project, plot.id, "error_bars", False, data, "Change error bars"
    ).apply(project)
    script = _assert_same(project, tmp_path)
    assert "sigma=" not in script  # unweighted now, as the figure's numbers are


def test_an_allan_deviation_in_hours_from_cycles_of_2_88_s(tmp_path: Path) -> None:
    # Cycles numbered 93, 94, ... each take 2.88 s; τ is shown in hours by a
    # formula that scales the cycles: 2.88 / 3600 = 0.0008 h per cycle.
    from figscribe.model import AllanDeviationPlot, Conversion

    rng = np.random.default_rng(12)
    y = rng.normal(scale=2e-12, size=400)
    rows = "\n".join(f"{93 + i},{float(v)!r}" for i, v in enumerate(y))
    (tmp_path / "cycles.csv").write_text(f"cycle,y\n{rows}\n", encoding="utf-8")
    source = csv_source(tmp_path / "cycles.csv", tmp_path, header_row=0)
    col = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    hours = Conversion(formula="x * 2.88 / 3600", unit="h")
    plot = AllanDeviationPlot(
        values=col["y"], time=col["cycle"], x_conversion=hours, x_range=(0.0, 0.2)
    )
    log = {"x": AxisSpec(scale="log"), "y": AxisSpec(scale="log")}
    project = Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(dpi=100, axes=[Axes(**log, artists=[plot])])],
    )
    script = _assert_same(project, tmp_path)
    assert "* 0.0008" in script or "/ 1250" in script  # 3600 / 2.88 = 1250


def test_a_mean_of_rows_with_a_fit_and_its_residuals(tmp_path: Path) -> None:
    from figscribe.model import Reduction

    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        label="data",
        left_out=[3, 20],
        reduction=Reduction(count=5, replace_left_out=True),
    )
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "from scipy.stats import binned_statistic" in script
    assert "group = rows[member] // 5" in script
    assert "binned_statistic(group, t[member]," in script
    assert "sigma=" in script and "absolute_sigma=True" in script


def test_derived_errors_with_units_a_range_and_a_dropped_last_group(
    tmp_path: Path,
) -> None:
    from figscribe.model import Conversion, Reduction

    project, ref = _run_csv(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        label="data",
        x_conversion=Conversion(factor=1 / 3600, from_start=True, unit="h"),
        x_range=(0.5, 3.5),
        left_out=[12],
        reduction=Reduction(count=4, keep_last=False),
    )
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    _assert_same(project, tmp_path)


def test_a_median_every_nth_row_and_intervals(tmp_path: Path) -> None:
    from figscribe.model import Reduction

    project, ref = _scan(tmp_path)
    median = LinePlot(
        x=ref["t"], y=ref["U"], reduction=Reduction(method="median", count=6)
    )
    every = ScatterPlot(
        x=ref["t"],
        y=ref["U"],
        left_out=[8],
        reduction=Reduction(method="every", count=4, replace_left_out=True),
    )
    interval = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        left_out=[5],
        reduction=Reduction(method="interval", width=1.3),
    )
    project.figures = [
        Figure(
            dpi=150,
            layout=GridLayout(rows=1, cols=2),
            axes=[Axes(artists=[median, every]), Axes(col=1, artists=[interval])],
        )
    ]
    _assert_same(project, tmp_path)


@pytest.mark.parametrize(
    "reduction",
    [
        {"method": "mean", "count": 4},
        {"method": "median", "count": 4},
        {"method": "every", "count": 4},
        {"method": "interval", "width": 1.3},
        {"method": "mean", "count": 4, "replace_left_out": True},
    ],
    ids=["mean", "median", "every", "interval", "mean-replacing"],
)
def test_a_reduced_plot_whose_range_keeps_no_row_draws_nothing(
    tmp_path: Path, reduction: dict
) -> None:
    """The renderer draws no point, so the script must not stop (B7.1)."""
    from figscribe.model import Reduction

    project, ref = _scan(tmp_path)
    nothing = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        left_out=[3],
        x_range=(1e6, 2e6),
        reduction=Reduction(**reduction),
    )
    other = LinePlot(x=ref["t"], y=ref["U"])
    project.figures = [Figure(dpi=100, axes=[Axes(artists=[nothing, other])])]
    _assert_same(project, tmp_path)


@pytest.mark.parametrize("reduced", [True, False], ids=["reduced", "plain"])
def test_a_fit_stays_when_the_range_is_narrowed_to_nothing(
    tmp_path: Path, reduced: bool
) -> None:
    """Fit first, then a range that keeps no row: the script must still run."""
    from figscribe.model import Reduction

    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        reduction=Reduction(count=4) if reduced else None,
    )
    project.figures = [Figure(dpi=100, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    data.x_range = (1e6, 2e6)
    _assert_same(project, tmp_path)


@pytest.mark.parametrize(
    "narrowing",
    ["fit range", "fit range, curve beyond it", "every row left out"],
)
def test_a_fit_with_no_point_left_is_not_drawn_and_the_script_says_so(
    tmp_path: Path, narrowing: str
) -> None:
    """Whatever leaves the fit nothing to run on, after it was run: no curve,
    no residual points, a script that runs and equals the figure."""
    project, ref = _scan(tmp_path)
    data = ErrorbarPlot(x=ref["t"], y=ref["U"], yerr=ref["dU"])
    project.figures = [Figure(dpi=100, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    fitted = next(a for a in project.figures[0].axes[0].artists if a.id == fit.id)
    if narrowing == "every row left out":
        data.left_out = list(range(len(load_data(project, tmp_path)(ref["t"]))))
    else:
        fitted.fit_range = (1e6, 2e6)
        fitted.extend_curve = narrowing != "fit range"
    script = _assert_same(project, tmp_path)
    assert "no point left to run on" in script
    assert "curve_fit(" not in script


def test_a_band_over_reduced_points_and_a_median_without_one(tmp_path: Path) -> None:
    from figscribe.model import Reduction

    project, ref = _scan(tmp_path)
    banded = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        linestyle="-",
        band=ErrorBand(),
        reduction=Reduction(count=4),
    )
    bare = ErrorbarPlot(
        x=ref["t"],
        y=ref["t2"],
        yerr=ref["dU"],
        linestyle="-",
        band=ErrorBand(),
        reduction=Reduction(method="median", count=4),
    )
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[banded, bare])])]
    _assert_same(project, tmp_path)


def test_a_formula_for_x_and_y_with_a_band_a_fit_and_a_range(tmp_path: Path) -> None:
    from figscribe.model import Conversion, ErrorBand

    project, ref = _run_csv(tmp_path)
    data = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        label="data",
        linestyle="-",
        band=ErrorBand(),
        x_conversion=Conversion(formula="x / 3600 + 1", from_start=True, unit="h"),
        y_conversion=Conversion(formula="(x - 0.1) / 7.5", unit="V"),
        x_range=(1.5, 4.5),
        left_out=[2, 30],
    )
    project.figures = [Figure(dpi=150, axes=[Axes(artists=[data])])]
    fit = FitCurve(target=data.id, model=PredefinedFit(name="gaussian"))
    add_fit(project, fit, residuals=True).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "t_h = (t - np.nanmin(t)) / 3600 + 1  # h since the start" in script
    assert "U_V = (U - 0.1) / 7.5  # in V" in script
    assert "dU_V = dU / 7.5" in script
    assert "used = (t_h >= 1.5) & (t_h <= 4.5)" in script


def test_a_formula_for_the_values_of_a_histogram(tmp_path: Path) -> None:
    from figscribe.model import Conversion, Histogram

    project, ref = _run_csv(tmp_path)
    counts = Histogram(
        values=ref["U"],
        bins=8,
        x_conversion=Conversion(formula="x * 1000 - 50", unit="mV"),
        x_range=(0.0, 900.0),
    )
    project.figures = [Figure(dpi=100, axes=[Axes(artists=[counts])])]
    script = _assert_same(project, tmp_path)
    assert "U * 1000 - 50" in script


def test_two_plots_of_one_column_with_different_formulas_do_not_share_a_variable(
    tmp_path: Path,
) -> None:
    from figscribe.model import Conversion

    project, ref = _run_csv(tmp_path)
    same_factor = {"unit": "V"}
    first = LinePlot(
        x=ref["t"], y=ref["U"], y_conversion=Conversion(formula="x + 1", **same_factor)
    )
    second = LinePlot(
        x=ref["t"], y=ref["U"], y_conversion=Conversion(formula="x - 1", **same_factor)
    )
    project.figures = [Figure(dpi=100, axes=[Axes(artists=[first, second])])]
    script = _assert_same(project, tmp_path)
    assert "U_V = U + 1" in script and "U_V2 = U - 1" in script


# --- the assistant's bench cases ---------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("case", bench.CASES, ids=[c.name for c in bench.CASES])
def test_bench_cases(case: bench.Case, tmp_path: Path) -> None:
    """What each bench case asks for, done by its reference solution, is drawn
    by the script as the renderer draws it."""
    from figscribe.examples import bundled_example

    folder = tmp_path / "bench"
    shutil.copytree(bundled_example(), folder)
    workspace = bench.example_workspace(folder)
    bench.apply_solution(case, workspace)
    assert case.check(workspace.project) is None  # it did what was asked
    for figure in workspace.project.figures:
        _assert_same(workspace.project, folder, figure)


# --- an axis drawn backwards ---------------------------------------------------


def _backwards(project: Project, ref, tmp_path: Path, **axes) -> str:
    """One panel of the scan with the given x and y specs, through the script."""
    panel = Axes(
        artists=[LinePlot(x=ref["t"], y=ref["U"], label="U")],
        legend=Legend(visible=True),
        **axes,
    )
    project.figures = [Figure(dpi=100, axes=[panel])]
    return _assert_same(project, tmp_path)


def test_an_automatic_range_drawn_backwards(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    script = _backwards(
        project, ref, tmp_path, x=AxisSpec(inverted=True), y=AxisSpec(inverted=True)
    )
    assert "ax.xaxis.set_inverted(True)" in script
    assert "ax.yaxis.set_inverted(True)" in script


def test_a_range_with_the_flag_is_written_highest_end_first(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    script = _backwards(
        project, ref, tmp_path, x=AxisSpec(limits=(0.0, 10.0), inverted=True)
    )
    assert "ax.set_xlim(10, 0)" in script and "inverted" not in script


def test_a_range_already_backwards_is_not_turned_back(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    script = _backwards(
        project, ref, tmp_path, x=AxisSpec(limits=(10.0, 0.0), inverted=True)
    )
    assert "ax.set_xlim(10, 0)" in script and "inverted" not in script


def test_a_log_axis_and_a_right_axis_drawn_backwards(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    _backwards(
        project,
        ref,
        tmp_path,
        x=AxisSpec(scale="log", limits=(0.5, 20.0), inverted=True),
        y_right=AxisSpec(label="T", inverted=True),
    )


@pytest.mark.parametrize("flagged", [(True, True), (True, False), (False, True)])
def test_panels_that_share_an_axis_drawn_backwards(
    tmp_path: Path, flagged: tuple[bool, bool]
) -> None:
    """The script must not toggle: both panels ask, and one reversal results."""
    project, ref = _scan(tmp_path)
    figure = _stacked_panels(ref)
    figure.layout = GridLayout(rows=2, share_x="col")
    figure.axes[0].x = AxisSpec(inverted=flagged[0])
    figure.axes[1].x = AxisSpec(inverted=flagged[1])
    project.figures = [figure]
    _assert_same(project, tmp_path)


# --- an open frame ---------------------------------------------------------------


def test_an_open_frame(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    figure = _stacked_panels(ref)
    figure.open_frame = True
    project.figures = [figure]
    script = _assert_same(project, tmp_path)
    assert '"axes.spines.top": False' in script and '"xtick.top": False' in script


def test_an_open_frame_with_a_right_axis_an_inset_and_a_colour_bar(
    tmp_path: Path,
) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, Colorbar, ImagePlot, Inset

    np.save(tmp_path / "frame.npy", np.arange(60.0).reshape(6, 10))
    frame = numpy_source(tmp_path / "frame.npy", tmp_path)
    project, ref = _scan(tmp_path)
    project.sources.append(frame)
    figure = _stacked_panels(ref)
    figure.open_frame = True
    figure.axes[0].y_right = AxisSpec(label="right", limits=(0.0, 1.0))
    figure.axes[1].artists = [
        ImagePlot(data=ArrayRef(source=frame.id), colorbar=Colorbar(label="counts"))
    ]
    figure.axes.append(
        Axes(
            inset=Inset(parent=figure.axes[0].id, bounds=(0.6, 0.6, 0.3, 0.3)),
            artists=[LinePlot(x=ref["t"], y=ref["U"])],
        )
    )
    project.figures = [figure]
    script = _assert_same(project, tmp_path)
    assert script.count('.spines["right"].set_visible(True)') == 1  # the right axis


def test_an_open_frame_over_a_style_sheet_with_ticks_on_top(tmp_path: Path) -> None:
    project, ref = _scan(tmp_path)
    figure = _stacked_panels(ref, stylesheet="classic")
    figure.open_frame = True
    project.figures = [figure]
    _assert_same(project, tmp_path)


# --- broken axes -------------------------------------------------------------


def _far(folder: Path):
    """Points from 0 to 20 and one far away at 420, with errors and a second
    quantity, also as whole numbers."""
    t = np.r_[np.linspace(0.0, 20.0, 11), 419.5]
    u = np.r_[1 + 0.1 * np.linspace(0.0, 20.0, 11), 9.0]
    rows = "\n".join(
        f"{a:.3f},{b:.4f},0.25,{10 * b:.4f},{int(a)}" for a, b in zip(t, u, strict=True)
    )
    (folder / "far.csv").write_text(f"t,U,dU,V,n\n{rows}\n", encoding="utf-8")
    source = csv_source(folder / "far.csv", folder)
    refs = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    return Project(sources=[source]), refs


_BROKEN = [(23.0, 416.0)]


@pytest.mark.parametrize(
    ("x", "y", "frame"),
    [
        (AxisSpec(label="t", breaks=_BROKEN), AxisSpec(label="U"), False),
        (AxisSpec(), AxisSpec(breaks=[(3.8, 8.0)]), False),
        (AxisSpec(breaks=_BROKEN), AxisSpec(breaks=[(3.8, 8.0)]), True),
        (AxisSpec(breaks=[(8.0, 12.0), (23.0, 416.0)]), AxisSpec(), False),
        (
            AxisSpec(breaks=_BROKEN, limits=(430.0, -3.0), major_step=5),
            AxisSpec(),
            False,
        ),
        (
            AxisSpec(
                breaks=_BROKEN, ticks=[0, 100, 419.5], tick_labels=["a", "b", "c"]
            ),
            AxisSpec(minor_ticks=False),
            False,
        ),
        (
            AxisSpec(breaks=_BROKEN, prefix="m", number_format="fixed", decimals=3),
            AxisSpec(breaks=[(3.8, 8.0)], minor_divisions=2),
            False,
        ),
        (AxisSpec(breaks=_BROKEN, inverted=True), AxisSpec(), True),
    ],
    ids=["x", "y", "both-open", "two", "range-step", "typed", "prefix", "inverted"],
)
def test_broken_axes(tmp_path: Path, x, y, frame) -> None:
    project, ref = _far(tmp_path)
    panel = Axes(
        x=x,
        y=y,
        grid=True,
        legend=Legend(visible=True, location="upper left"),
        artists=[
            ErrorbarPlot(
                x=ref["t"], y=ref["U"], yerr=ref["dU"], linestyle="-", label="data"
            ),
        ],
    )
    project.figures = [
        Figure(
            dpi=110, width_mm=120, open_frame=frame, decimal_comma=frame, axes=[panel]
        )
    ]
    script = _assert_same(project, tmp_path)
    assert "def cut_out(" in script
    assert "across_breaks(" in script  # no line across a break
    assert "np.insert(t, [" not in script  # nor row numbers of today's data
    assert [line for line in script.splitlines() if len(line) > 88] == []


@pytest.mark.parametrize("band", [False, True])
def test_a_broken_axis_with_a_fit_left_out_rows_and_residuals(
    tmp_path: Path, band
) -> None:
    project, ref = _far(tmp_path)
    plot = ErrorbarPlot(
        x=ref["t"],
        y=ref["U"],
        yerr=ref["dU"],
        linestyle="-",
        label="data",
        left_out=[3],
        band=ErrorBand() if band else None,
    )
    fit = FitCurve(target=plot.id, model=PredefinedFit(name="linear"), label="fit")
    top = Axes(x=AxisSpec(breaks=_BROKEN), artists=[plot, fit])
    project.figures = [
        Figure(
            dpi=110,
            height_mm=90,
            layout=GridLayout(rows=2, share_x="col", height_ratios=[3, 1]),
            axes=[
                top,
                Axes(
                    row=1,
                    artists=[ResidualPlot(target=fit.id, linestyle="-")],
                ),
            ],
        )
    ]
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "np.concatenate(" in script
    assert script.count('set_xscale("function"') == 1  # shared between the two


def test_a_broken_x_axis_with_a_right_axis_marks_and_integers(tmp_path: Path) -> None:
    project, ref = _far(tmp_path)
    panel = Axes(
        x=AxisSpec(breaks=_BROKEN),
        y_right=AxisSpec(label="V"),
        artists=[
            LinePlot(x=ref["n"], y=ref["U"], marker="o"),
            LinePlot(x=ref["n"], y=ref["V"], axis="right", color="C3"),
            ReferenceLine(orientation="horizontal", at=5.0),
            ShadedSpan(start=10.0, end=200.0),
        ],
    )
    project.figures = [Figure(dpi=110, width_mm=120, axes=[panel])]
    script = _assert_same(project, tmp_path)
    assert "twin=ax_right" in script


def test_broken_axes_of_scatter_histogram_and_mesh(tmp_path: Path) -> None:
    from figscribe.io import numpy_source
    from figscribe.model import ArrayRef, ColorMesh

    project, ref = _far(tmp_path)
    np.save(tmp_path / "z.npy", np.arange(20.0).reshape(4, 5))
    frame = numpy_source(tmp_path / "z.npy", tmp_path)
    project.sources.append(frame)
    project.figures = [
        Figure(
            dpi=110,
            width_mm=175,
            layout=GridLayout(cols=3),
            axes=[
                Axes(
                    x=AxisSpec(breaks=_BROKEN),
                    artists=[ScatterPlot(x=ref["t"], y=ref["U"])],
                ),
                Axes(
                    col=1,
                    x=AxisSpec(breaks=_BROKEN),
                    artists=[Histogram(values=ref["t"], bins=30)],
                ),
                Axes(
                    col=2,
                    x=AxisSpec(breaks=[(1.5, 3.5)]),
                    artists=[ColorMesh(c=ArrayRef(source=frame.id))],
                ),
            ],
        )
    ]
    script = _assert_same(project, tmp_path)
    assert "= across_breaks(" not in script  # no lines to cut


@pytest.mark.parametrize(
    "plot",
    [
        {"reduction": Reduction(method="mean", count=3)},
        {"x_conversion": Conversion(factor=2.0)},
        {"x_range": (1.0, 420.0)},
    ],
    ids=["reduced", "converted", "range"],
)
def test_a_broken_line_of_data_changed_before_it_is_drawn(tmp_path: Path, plot) -> None:
    """The breaks cut the arrays the script plots, not the rows of the file."""
    project, ref = _far(tmp_path)
    breaks = [(46.0, 700.0)] if "x_conversion" in plot else _BROKEN
    line = LinePlot(x=ref["t"], y=ref["U"], marker="o", **plot)
    panel = Axes(x=AxisSpec(breaks=breaks), artists=[line])
    project.figures = [Figure(dpi=110, width_mm=120, axes=[panel])]
    _assert_same(project, tmp_path)


def test_the_script_cuts_other_data_where_its_breaks_are(tmp_path: Path) -> None:
    """With the hash check deleted and a row more, the line is still cut where
    it crosses the break."""
    project, ref = _far(tmp_path)
    panel = Axes(x=AxisSpec(breaks=_BROKEN), artists=[LinePlot(x=ref["t"], y=ref["U"])])
    project.figures = [Figure(dpi=110, axes=[panel])]
    script = _assert_same(project, tmp_path)
    path = tmp_path / "far.csv"
    header, first, *rows = path.read_text(encoding="utf-8").splitlines()
    more = [header, first, first, *rows]  # the break is a row further down
    path.write_text("\n".join(more) + "\n", encoding="utf-8")
    start, end = script.index("if hashlib"), script.index("raise SystemExit")
    unchecked = script[:start] + "if False:\n    " + script[end:]
    unchecked = unchecked.replace(
        'fig.savefig(HERE / "from_script.png")',
        "(line,) = [a for a in ax.lines if a.get_gid() is None][:1]\n"
        "x = line.get_xdata()\n"
        "at = int(np.flatnonzero(np.isnan(x))[0])\n"
        "assert (x[at - 1], x[at + 1]) == (20.0, 419.5), x\n"
        'fig.savefig(HERE / "from_script.png")',
    )
    _run(unchecked, tmp_path)


def _with_a_near_point(folder: Path):
    """_far with a point past 29, so that a line leaves a range ending at 22."""
    project, _ = _far(folder)
    path = folder / "far.csv"
    text = path.read_text(encoding="utf-8") + "29.760,3.5000,0.25,35.0000,29\n"
    rows = text.splitlines()
    rows[-2], rows[-1] = rows[-1], rows[-2]  # in the order of t
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    source = csv_source(path, folder)
    refs = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    return Project(sources=[source]), refs


@pytest.mark.parametrize("limits", [(0.0, 22.0), (40.0, 400.0)])
@pytest.mark.parametrize("beside", [False, True])
def test_a_break_the_typed_range_does_not_show(tmp_path, limits, beside) -> None:
    """Also beside a panel whose axis is broken, which makes the script cut."""
    project, ref = _with_a_near_point(tmp_path)
    line = LinePlot(x=ref["t"], y=ref["U"], marker="o")
    panels = [Axes(x=AxisSpec(breaks=_BROKEN, limits=limits), artists=[line])]
    if beside:
        other = LinePlot(x=ref["t"], y=ref["U"])
        panels.append(Axes(col=1, x=AxisSpec(breaks=_BROKEN), artists=[other]))
    layout = GridLayout(cols=len(panels))
    project.figures = [Figure(dpi=110, width_mm=160, layout=layout, axes=panels)]
    _assert_same(project, tmp_path)


def _noise(folder: Path):
    values = np.random.default_rng(1).normal(size=2000)
    rows = "\n".join(f"{v:.6f}" for v in values)
    (folder / "noise.csv").write_text(f"y\n{rows}\n", encoding="utf-8")
    source = csv_source(folder / "noise.csv", folder)
    return Project(sources=[source]), ColumnRef(source=source.id, column="y")


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (AxisSpec(breaks=[(70.0, 120.0)]), AxisSpec()),
        (AxisSpec(), AxisSpec(breaks=[(0.12, 0.2)])),
    ],
    ids=["x", "y"],
)
def test_an_allan_deviation_on_a_broken_axis(tmp_path: Path, x, y) -> None:
    project, values = _noise(tmp_path)
    panel = Axes(x=x, y=y, artists=[AllanDeviationPlot(values=values)])
    project.figures = [Figure(dpi=110, width_mm=120, axes=[panel])]
    script = _assert_same(project, tmp_path)
    assert "= across_breaks(" in script


@pytest.mark.parametrize("gap", [(0.081, 0.108), (2.0, 3.0)], ids=["cuts", "above"])
def test_an_allan_fit_with_only_y_broken(tmp_path: Path, gap) -> None:
    """The curve is sampled evenly in log τ, as on a whole axis."""
    project, values = _noise(tmp_path)
    plot = AllanDeviationPlot(values=values)
    fit = FitCurve(
        target=plot.id,
        model=ExpressionFit(expression="a / sqrt(x)", parameters=["a"]),
    )
    panel = Axes(
        x=AxisSpec(scale="log"),
        y=AxisSpec(breaks=[gap]),
        artists=[plot, fit],
    )
    project.figures = [Figure(dpi=110, width_mm=120, axes=[panel])]
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    script = _assert_same(project, tmp_path)
    assert "np.geomspace(" in script


def test_the_script_keeps_the_tick_step_of_a_broken_axis(tmp_path: Path) -> None:
    project, ref = _far(tmp_path)
    x = AxisSpec(prefix="m", breaks=_BROKEN, major_step=2.0)
    panel = Axes(x=x, artists=[LinePlot(x=ref["t"], y=ref["U"])])
    project.figures = [Figure(dpi=110, width_mm=160, axes=[panel])]
    script = _assert_same(project, tmp_path)
    assert "if abs(v) >" in script  # zero is written as 0, as the preview does


def _inside(folder: Path):
    """x from 100 to 200: all of it within a break from 24 to 416."""
    rows = "\n".join(f"{t},{t / 100}" for t in range(100, 201, 10))
    (folder / "inside.csv").write_text(f"t,U\n{rows}\n", encoding="utf-8")
    source = csv_source(folder / "inside.csv", folder)
    refs = {c: ColumnRef(source=source.id, column=c) for c in source.columns}
    return Project(sources=[source]), refs


def test_data_all_within_a_break(tmp_path: Path) -> None:
    project, ref = _inside(tmp_path)
    x = AxisSpec(breaks=[(24.0, 416.0)])
    panel = Axes(x=x, artists=[LinePlot(x=ref["t"], y=ref["U"])])
    project.figures = [Figure(dpi=110, width_mm=120, axes=[panel])]
    _assert_same(project, tmp_path)


def test_a_tick_step_too_fine_for_an_axis_drawn_whole_stays_out(tmp_path) -> None:
    """Not run: with the step in it, the script would take minutes."""
    project, ref = _inside(tmp_path)
    x = AxisSpec(breaks=[(24.0, 416.0)], major_step=0.001)
    panel = Axes(x=x, artists=[LinePlot(x=ref["t"], y=ref["U"])])
    project.figures = [Figure(axes=[panel])]
    data = load_data(project, tmp_path)
    script = generate(project, project.figures[0], base_dir=tmp_path, data=data)
    assert "MultipleLocator" not in script


def test_shared_panels_with_two_ranges(tmp_path: Path) -> None:
    """The range typed last, 140 to 160, is the one the axis has, and it lies
    within the break."""
    project, ref = _inside(tmp_path)
    line = LinePlot(x=ref["t"], y=ref["U"])
    panels = [
        Axes(
            row=row,
            x=AxisSpec(breaks=[(130.0, 170.0)], limits=limits),
            artists=[line.model_copy(update={"id": f"line{row}"})],
        )
        for row, limits in enumerate([(100.0, 200.0), (140.0, 160.0)])
    ]
    layout = GridLayout(rows=2, share_x="col")
    project.figures = [Figure(dpi=110, layout=layout, axes=panels)]
    _assert_same(project, tmp_path)
