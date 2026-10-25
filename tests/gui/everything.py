"""A project with every kind of object the property panel edits, written to
disk with its data files, for tests that go through all of them."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from figscribe.commands import History
from figscribe.fit import add_fit, refit
from figscribe.io import csv_source, load_data
from figscribe.io.numpyfile import numpy_source
from figscribe.model import (
    Annotation,
    ArrayRef,
    Axes,
    AxisSpec,
    Colorbar,
    ColorMesh,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    FitCurve,
    GridLayout,
    Histogram,
    ImagePlot,
    Inset,
    Legend,
    LinePlot,
    PredefinedFit,
    Project,
    ResidualPlot,
    ScatterPlot,
    dumps,
)


def build(folder: Path) -> Path:
    """Write the project and its files into `folder`; return the project file.

    Panel A has a line, points, error bars with a fit, a note with an arrow
    and a right y axis with a plot on it; B a histogram and the residuals; C
    an image and D a color mesh, both with color bars; E is an inset in A.
    Everything that can be switched off is on, so that its settings show.
    """
    t = np.linspace(0.0, 4.0, 21)
    rows = ["t,U,dU,T", "s,V,V,K"] + [
        f"{x:.2f},{1.0 + 2.0 * x + 0.1 * np.sin(5 * x):.5f},0.1,{300 + 5 * x:.1f}"
        for x in t
    ]
    (folder / "scan.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    y, x = np.mgrid[0:12, 0:16]
    np.savez(
        folder / "map.npz",
        counts=np.exp(-((x - 8.0) ** 2 + (y - 6.0) ** 2) / 20.0) + 0.01,
        background=0.1 + 0.01 * x + 0.02 * y,
        x=np.arange(16.0),
        y=np.arange(12.0),
    )
    scan = csv_source(folder / "scan.csv", folder, header_row=0, skip_rows=1)
    grid = numpy_source(folder / "map.npz", folder, array="counts")

    def col(name: str) -> ColumnRef:
        return ColumnRef(source=scan.id, column=name)

    errorbars = ErrorbarPlot(x=col("t"), y=col("U"), yerr=col("dU"), label="data")
    a = Axes(
        title="Scan",
        grid=True,
        x=AxisSpec(label="t", unit="s"),
        y=AxisSpec(label="U", unit="V"),
        y_right=AxisSpec(label="T", unit="K"),
        legend=Legend(visible=True),
        artists=[
            errorbars,
            LinePlot(x=col("t"), y=col("U"), marker="x", label="line"),
            ScatterPlot(x=col("t"), y=col("U"), label="points"),
            LinePlot(x=col("t"), y=col("T"), axis="right", label="temperature"),
            Annotation(text="peak", position=(2.0, 5.0), arrow_to=(2.5, 6.0)),
        ],
    )
    b = Axes(
        col=1,
        legend=Legend(visible=True),
        artists=[Histogram(values=col("U"), label="counts")],
    )
    c = Axes(
        row=1,
        artists=[ImagePlot(data=ArrayRef(source=grid.id), colorbar=Colorbar())],
    )
    d = Axes(
        row=1,
        col=1,
        artists=[ColorMesh(c=ArrayRef(source=grid.id), colorbar=Colorbar())],
    )
    e = Axes(
        title="Detail",
        inset=Inset(parent=a.id, bounds=(0.6, 0.15, 0.35, 0.35)),
        legend=Legend(visible=True),
        grid=True,
        artists=[
            LinePlot(x=col("t"), y=col("U"), label="detail"),
            LinePlot(x=col("t"), y=col("dU"), label="error"),
        ],
    )
    figure = Figure(
        width_mm=175,
        height_mm=120,
        layout=GridLayout(rows=2, cols=2),
        axes=[a, b, c, d, e],
    )
    project = Project(sources=[scan, grid], figures=[figure])

    history = History(project)
    fit = FitCurve(
        target=errorbars.id, model=PredefinedFit(name="linear"), fit_range=(0.5, 3.5)
    )
    history.push(add_fit(project, fit))
    history.push(refit(project, fit.id, load_data(project, folder)))
    project.figures[0].axes[1].artists.append(ResidualPlot(target=fit.id))

    path = folder / "everything.figscribe"
    path.write_text(dumps(project), encoding="utf-8")
    return path
