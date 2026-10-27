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

from figscribe.codegen import generate
from figscribe.commands import add_panel
from figscribe.fit import add_fit, refit
from figscribe.io import load_data
from figscribe.io.csvfile import csv_source
from figscribe.model import (
    Axes,
    AxisSpec,
    ColumnRef,
    ErrorBand,
    ErrorbarPlot,
    Figure,
    FitCurve,
    GridLayout,
    Histogram,
    Legend,
    LinePlot,
    PanelLabels,
    PredefinedFit,
    Project,
    ReferenceLine,
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


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
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
    assert 'ax.grid(True, which="both", axis="y")' in script


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
    assert 'f"{v * 1e3:g}"' in script and 'f"{v / 1e3:g}"' in script
    assert '"t (ms)"' in script


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
    assert 'ax.grid(True, which="both", linewidth=0.4, linestyle=":")' in script


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
    rows = "\n".join(f"{a!r},{b:.5f},0.030" for a, b in zip(t, u, strict=True))
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
