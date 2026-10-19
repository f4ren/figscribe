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
    ErrorbarPlot,
    Figure,
    FitCurve,
    GridLayout,
    Legend,
    LinePlot,
    PredefinedFit,
    Project,
    ScatterPlot,
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
