"""Writes the example projects of figscribe (decision 0053).

Run `python examples/make.py` from a checkout; it rewrites every folder next to
this file: the data (synthetic, from a fixed seed), the project, a thumbnail for
the start page and `index.json`. The projects are built through the model, as
the program would, and the fits are run, so each opens with its results.

Nothing here is read from a measurement: the numbers are made up to show what
the program can do.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import uuid
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from xml.sax.saxutils import escape, quoteattr

import numpy as np
from PIL import Image

from figscribe.commands import History
from figscribe.fit import add_fit, refit
from figscribe.io import csv_source, load_data
from figscribe.io.numpyfile import numpy_source
from figscribe.io.sheetfile import sheet_source
from figscribe.model import (
    AllanDeviationPlot,
    Annotation,
    ArrayRef,
    Axes,
    AxisSpec,
    Colorbar,
    ColorMesh,
    ColumnRef,
    Conversion,
    CsvSource,
    DataSource,
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
    ScatterPlot,
    ShadedSpan,
    dumps,
    loads,
)
from figscribe.render import export

HERE = Path(__file__).resolve().parent
CREATED = datetime(2026, 11, 1, tzinfo=UTC)
VERSION = "0.2.0"
THUMBNAIL_PX = 520
THUMBNAIL_HEIGHT_PX = 340
"""The size of the picture shown for an example on the start page."""


# --- helpers ------------------------------------------------------------------


@contextlib.contextmanager
def fixed_ids(seed: int) -> Iterator[None]:
    """Object ids that are the same on every run: the ids are `uuid4`s."""
    rng = np.random.default_rng(seed)
    real = uuid.uuid4
    uuid.uuid4 = lambda: uuid.UUID(bytes=rng.bytes(16))  # type: ignore[assignment]
    try:
        yield
    finally:
        uuid.uuid4 = real  # type: ignore[assignment]


def write_csv(
    folder: Path,
    name: str,
    columns: dict[str, np.ndarray],
    *,
    units: list[str] | None = None,
    comment: str | None = None,
) -> CsvSource:
    """A CSV file as bytes with `\\n`, so its SHA-256 is the same on every
    platform, and the source that records it."""
    lines = [f"# {comment}"] if comment else []
    lines.append(",".join(columns))
    if units:
        lines.append(",".join(units))
    count = len(next(iter(columns.values())))
    for i in range(count):
        lines.append(",".join(f"{columns[name][i]:.6g}" for name in columns))
    (folder / name).write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return csv_source(
        folder / name,
        folder,
        header_row=1 if comment else 0,
        skip_rows=1 if units else 0,
    )


class Formula(NamedTuple):
    """A computed cell: the formula, written as A1 references, and the number
    the spreadsheet stores for it (None: stored without one)."""

    text: str
    value: float | None


def write_ods(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    """A LibreOffice Calc file of the sheets' rows, written with the standard
    library so that the examples need no further package. Cells are numbers,
    text, True or False, datetimes, `Formula`s or None for empty. The bytes are
    the same on every run, so the hash in the project holds."""
    tables = []
    for name, rows in sheets.items():
        lines = [
            "<table:table-row>"
            + "".join(map(_ods_cell, row or [None]))
            + "</table:table-row>"
            for row in rows
        ]
        tables.append(
            f"<table:table table:name={quoteattr(name)}>{''.join(lines)}</table:table>"
        )
    spaces = " ".join(
        f'xmlns:{prefix}="urn:oasis:names:tc:opendocument:xmlns:{what}:1.0"'
        for prefix, what in (("office", "office"), ("table", "table"), ("text", "text"))
    )
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<office:document-content {spaces} "
        'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" '
        'office:version="1.2"><office:body><office:spreadsheet>'
        f"{''.join(tables)}"
        "</office:spreadsheet></office:body></office:document-content>"
    )
    kind = "application/vnd.oasis.opendocument.spreadsheet"
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?><manifest:manifest '
        'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2">'
        f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{kind}"/>'
        '<manifest:file-entry manifest:full-path="content.xml" '
        'manifest:media-type="text/xml"/></manifest:manifest>'
    )
    # Nothing is compressed: zlib differs between platforms, and the file's hash
    # is in the project. "mimetype" comes first, so that the file is known.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
        for name, text in (
            ("mimetype", kind),
            ("content.xml", content),
            ("META-INF/manifest.xml", manifest),
        ):
            entry = zipfile.ZipInfo(name, date_time=(2026, 11, 1, 0, 0, 0))
            entry.create_system = 3  # the same bytes written on Windows
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, text)


def _ods_cell(value: object) -> str:
    formula = ""
    if isinstance(value, Formula):
        inner = re.sub(
            r"\b([A-Z]+[0-9]+)(?::([A-Z]+[0-9]+))?\b(?!\()",
            lambda m: f"[.{m[1]}:.{m[2]}]" if m[2] else f"[.{m[1]}]",
            value.text,
        )
        formula = f" table:formula={quoteattr('of:=' + inner)}"
        value = value.value
    if value is None:
        return f"<table:table-cell{formula}/>"
    if isinstance(value, bool):
        kind, attribute, shown = "boolean", "boolean-value", str(value).lower()
    elif isinstance(value, datetime):
        kind, attribute, shown = "date", "date-value", value.isoformat()
    elif isinstance(value, str):
        kind, attribute, shown = "string", None, value
    else:
        kind, attribute, shown = "float", "value", repr(float(value))
    number = f' office:{attribute}="{shown}"' if attribute else ""
    return (
        f'<table:table-cell{formula} office:value-type="{kind}"{number}>'
        f"<text:p>{escape(shown)}</text:p></table:table-cell>"
    )


def column(source: DataSource, name: str | int) -> ColumnRef:
    return ColumnRef(source=source.id, column=name)


def project_of(sources: list[DataSource], *figures: Figure) -> Project:
    return Project(
        figscribe_version=VERSION,
        created=CREATED,
        sources=sources,
        figures=list(figures),
    )


def fit_to(
    project: Project,
    folder: Path,
    plot,
    model,
    *,
    residuals: bool = False,
    **options,
) -> FitCurve:
    """Add a fit of `plot` and run it, as the fit dialog does."""
    fit = FitCurve(target=plot.id, model=model, **options)
    history = History(project)
    history.push(add_fit(project, fit, residuals))
    history.push(refit(project, fit.id, load_data(project, folder)))
    return next(
        artist
        for figure in project.figures
        for axes in figure.axes
        for artist in axes.artists
        if artist.id == fit.id
    )


def axis(label: str, unit: str | None = None, **options) -> AxisSpec:
    return AxisSpec(label=label, unit=unit, **options)


# --- the examples -------------------------------------------------------------


def noisy_sensor(folder: Path) -> Project:
    """A long noisy series: thin and grey, and on top the same column with
    fewer points, each the mean of a minute with its standard error."""
    rng = np.random.default_rng(101)
    t = np.arange(0.0, 3000.0)  # s, one reading a second
    warm_up = 6.0 * np.exp(-t / 120.0)
    signal = 20.0 + 1.5 * np.sin(2 * np.pi * t / 1500.0) + warm_up
    signal += rng.normal(0.0, 0.9, t.size)
    source = write_csv(
        folder,
        "sensor.csv",
        {"t": t, "signal": signal},
        units=["s", "mV"],
        comment="Synthetic sensor reading, one value a second",
    )
    minutes = Conversion(factor=1 / 60, from_start=True, unit="min")
    raw = LinePlot(
        x=column(source, "t"),
        y=column(source, "signal"),
        label="every reading",
        color="0.75",
        linewidth=0.4,
        x_conversion=minutes,
        x_range=(4.0, 49.0),
    )
    mean = ErrorbarPlot(
        x=column(source, "t"),
        y=column(source, "signal"),
        label="mean of a minute ± standard error",
        color="C0",
        marker="o",
        markersize=3.0,
        capsize=0.0,
        elinewidth=0.8,
        x_conversion=minutes,
        x_range=(4.0, 49.0),
        reduction=Reduction(method="mean", count=60),
    )
    panel = Axes(
        x=axis("Time", "min", limits=(4.0, 49.0)),
        y=axis("Signal", "mV"),
        legend=Legend(visible=True, location="upper right", frame=False),
        grid=True,
        grid_color="0.9",
        artists=[raw, mean],
    )
    figure = Figure(name="Sensor", width_mm=100, height_mm=62, dpi=300, axes=[panel])
    return project_of([source], figure)


def rc_discharge(folder: Path) -> Project:
    """An exponential decay with one glitch left out and a fit with its
    residuals; the offset is held."""
    rng = np.random.default_rng(102)
    t = np.linspace(0.0, 0.005, 60)  # s
    volts = 4.2 * np.exp(-t / 0.0012) + rng.normal(0.0, 0.05, t.size)
    volts[21] += 1.1  # a switching spike
    source = write_csv(
        folder,
        "discharge.csv",
        {"t": t, "U": volts, "dU": np.full(t.size, 0.05)},
        units=["s", "V", "V"],
        comment="Synthetic RC discharge",
    )
    data = ErrorbarPlot(
        x=column(source, "t"),
        y=column(source, "U"),
        yerr=column(source, "dU"),
        label="capacitor voltage",
        color="C3",
        marker="s",
        markersize=3.5,
        left_out=[21],
        left_out_color="0.55",
        left_out_marker="x",
        left_out_note="row 22: a switching spike",
        x_conversion=Conversion(factor=1000.0, unit="ms"),
    )
    panel = Axes(
        x=axis("Time", "ms"),
        y=axis("Voltage", "V"),
        legend=Legend(visible=True, location="upper right"),
        artists=[data],
    )
    figure = Figure(
        name="Discharge",
        width_mm=100,
        height_mm=80,
        layout=GridLayout(rows=1, cols=1),
        axes=[panel],
    )
    project = project_of([source], figure)
    fit = fit_to(
        project,
        folder,
        data,
        PredefinedFit(name="exponential"),
        residuals=True,
        initial_values={"a": 4.0, "tau": 1.0, "c": 0.0},
        fixed=["c"],
        fit_range=(0.2, 5.0),
        color="C0",
        label="exponential, offset held at 0",
    )
    residual = next(
        artist
        for artist in project.figures[0].axes[1].artists
        if artist.kind == "residual"
    )
    residual.zero_color = "C3"
    residual.zero_linestyle = ":"
    residual.zero_linewidth = 1.2
    residual.color = "C0"
    assert fit.result is not None
    return project


def freezing_plateau(folder: Path) -> Project:
    """A freezing curve shown in hours and degrees Celsius from data in s
    and K, with its plateau, a fixed point and the heater on a second axis."""
    rng = np.random.default_rng(103)
    t = np.arange(0.0, 9 * 3600.0, 60.0)  # s, a reading a minute
    point = 692.677  # K
    kelvin = np.empty_like(t)
    for i, h in enumerate(t / 3600.0):
        if h < 1.0:  # supercooling, below the point
            kelvin[i] = point + 3.0 - 7.0 * h
        elif h < 1.4:  # recalescence back to the point
            kelvin[i] = point - 4.0 + (h - 1.0) / 0.4 * 4.02
        elif h < 5.0:  # the plateau, falling a little
            kelvin[i] = point + 0.02 - 0.0035 * (h - 1.4)
        else:  # cooling away
            kelvin[i] = point + 0.007 - 14.0 * (1.0 - np.exp(-(h - 5.0) / 0.9))
    kelvin += rng.normal(0.0, 0.004, t.size)
    power = 12.0 + 6.0 * np.exp(-(((t / 3600.0) - 1.2) ** 2) / 0.3)
    power += rng.normal(0.0, 0.15, t.size)
    source = write_csv(
        folder,
        "furnace.csv",
        {"t": t, "T": kelvin, "P": power},
        units=["s", "K", "W"],
        comment="Synthetic freezing curve of a fixed-point cell",
    )
    hours = Conversion(factor=1 / 3600, from_start=True, unit="h")
    temperature = LinePlot(
        x=column(source, "t"),
        y=column(source, "T"),
        label="cell",
        color="C0",
        linewidth=1.0,
        x_conversion=hours,
        y_conversion=Conversion(formula="x - 273.15", unit="°C"),
        reduction=Reduction(method="mean", count=5),
    )
    heater = LinePlot(
        x=column(source, "t"),
        y=column(source, "P"),
        label="heater power",
        color="C1",
        linewidth=0.8,
        axis="right",
        x_conversion=hours,
        reduction=Reduction(method="mean", count=5),
    )
    panel = Axes(
        x=axis("Time since the start", "h", limits=(0.0, 9.0)),
        y=axis("Temperature", "°C", limits=(410.0, 428.0)),
        y_right=axis("Heater power", "W", limits=(8.0, 26.0)),
        legend=Legend(visible=True, location="upper right"),
        artists=[
            ShadedSpan(
                start=1.6, end=4.6, color="C2", alpha=0.18, label="plateau, 3 h"
            ),
            ReferenceLine(
                at=419.527,
                orientation="horizontal",
                color="C3",
                linestyle="--",
                linewidth=0.9,
                label="Zn fixed point, 419.527 °C",
            ),
            temperature,
            heater,
            Annotation(
                text="recalescence",
                position=(1.7, 413.0),
                arrow_to=(1.25, 417.6),
                background="white",
                fontsize=7,
            ),
        ],
    )
    figure = Figure(
        name="Freezing curve", width_mm=110, height_mm=70, axes=[panel], font_size=8
    )
    return project_of([source], figure)


def resonance(folder: Path) -> Project:
    """Amplitude and phase of a resonator against frequency, in two panels
    that share a logarithmic axis; the amplitude has a Lorentzian with
    bounds."""
    rng = np.random.default_rng(104)
    f = np.geomspace(5e3, 2e4, 90)  # Hz
    f0, gamma = 1.0e4, 450.0
    amplitude = 2.0 * gamma**2 / ((f - f0) ** 2 + gamma**2) + 0.04
    amplitude += rng.normal(0.0, 0.03, f.size)
    phase = -np.degrees(np.arctan2(2 * f * gamma, f0**2 - f**2))
    phase += rng.normal(0.0, 1.5, f.size)
    source = write_csv(
        folder,
        "resonator.csv",
        {"f": f, "A": amplitude, "dA": np.full(f.size, 0.03), "phi": phase},
        units=["Hz", "V", "V", "deg"],
        comment="Synthetic resonator sweep",
    )
    amp = ErrorbarPlot(
        x=column(source, "f"),
        y=column(source, "A"),
        yerr=column(source, "dA"),
        label="amplitude",
        color="C2",
        marker="o",
        markersize=2.5,
        capsize=0.0,
        elinewidth=0.6,
    )
    ph = ScatterPlot(
        x=column(source, "f"),
        y=column(source, "phi"),
        label="phase",
        color="C4",
        size=6.0,
    )
    top = Axes(
        row=0,
        x=axis(
            "Frequency",
            "Hz",
            scale="log",
            prefix="k",
            limits=(5e3, 2e4),
            ticks=[5e3, 7e3, 1e4, 1.4e4, 2e4],
        ),
        y=axis("Amplitude", "V"),
        legend=Legend(visible=True, location="upper left", frame=False),
        artists=[amp],
    )
    bottom = Axes(
        row=1,
        x=axis(
            "Frequency",
            "Hz",
            scale="log",
            prefix="k",
            limits=(5e3, 2e4),
            ticks=[5e3, 7e3, 1e4, 1.4e4, 2e4],
        ),
        y=axis("Phase", "°", limits=(-200.0, 20.0)),
        grid=True,
        grid_color="0.88",
        artists=[ph],
    )
    figure = Figure(
        name="Resonance",
        width_mm=100,
        height_mm=95,
        unit_format="slash",
        layout=GridLayout(rows=2, cols=1, share_x="col", height_ratios=[2.0, 1.0]),
        panel_labels=PanelLabels(style="a)", bold=True),
        axes=[top, bottom],
    )
    project = project_of([source], figure)
    fit_to(
        project,
        folder,
        amp,
        PredefinedFit(name="lorentzian"),
        initial_values={"a": 2.0, "x0": 1.0e4, "gamma": 400.0, "c": 0.0},
        parameter_bounds={"gamma": (1.0, 5000.0), "c": (0.0, 0.5)},
        color="C3",
        linewidth=1.2,
        label="Lorentzian",
    )
    return project


def diode_iv(folder: Path) -> Project:
    """A diode's current over many decades, on a symmetric log axis with
    its linear zone around zero, and a fit with an expression of one's own."""
    rng = np.random.default_rng(105)
    v = np.linspace(-1.0, 0.75, 70)
    saturation, ideality, thermal = 2.0e-9, 1.8, 0.02585
    current = saturation * (np.exp(v / (ideality * thermal)) - 1.0)
    current = current * (1.0 + rng.normal(0.0, 0.04, v.size))
    current += rng.normal(0.0, 3.0e-10, v.size)  # the meter's noise floor
    source = write_csv(
        folder,
        "diode.csv",
        {"V": v, "I": current},
        units=["V", "A"],
        comment="Synthetic current-voltage curve of a diode",
    )
    points = ScatterPlot(
        x=column(source, "V"),
        y=column(source, "I"),
        label="measured",
        color="C0",
        marker="o",
        size=7.0,
        alpha=0.8,
    )
    panel = Axes(
        x=axis("Voltage", "V", limits=(-1.0, 0.8)),
        y=axis(
            "Current",
            "A",
            scale="symlog",
            symlog_linthresh=1.0e-8,
            limits=(-1.0e-8, 1.0),
        ),
        legend=Legend(visible=True, location="upper left"),
        grid=True,
        grid_which="major",
        grid_linestyle=":",
        artists=[points],
    )
    figure = Figure(name="Diode", width_mm=90, height_mm=70, axes=[panel])
    project = project_of([source], figure)
    fit_to(
        project,
        folder,
        points,
        ExpressionFit(expression="a * (exp(x / b) - 1)", parameters=["a", "b"]),
        initial_values={"a": 2.0e-9, "b": 0.05},
        fit_range=(0.2, 0.75),
        color="C3",
        label="a (exp(V / b) - 1)",
    )
    return project


def growth_curve(folder: Path) -> Project:
    """Five replicates of a culture, each with a marker of its own, hours
    shown as days, and a logistic curve fitted to the first."""
    rng = np.random.default_rng(106)
    t = np.arange(0.0, 49.0, 1.0)  # h
    columns: dict[str, np.ndarray] = {"t": t}
    for k in range(5):
        capacity = 1.15 + 0.08 * rng.normal()
        rate = 0.24 + 0.02 * rng.normal()
        midpoint = 19.0 + 1.2 * rng.normal()
        od = capacity / (1.0 + np.exp(-rate * (t - midpoint)))
        columns[f"OD{k + 1}"] = od + rng.normal(0.0, 0.015, t.size) + 0.02
    source = write_csv(
        folder,
        "growth.csv",
        columns,
        units=["h", *["1"] * 5],
        comment="Synthetic growth of five replicate cultures",
    )
    days = Conversion(factor=1 / 24, unit="d")
    markers = ["o", "s", "^", "D", "v"]
    plots = [
        ScatterPlot(
            x=column(source, "t"),
            y=column(source, f"OD{k + 1}"),
            label=f"replicate {k + 1}",
            marker=markers[k],
            size=14.0,
            color=f"C{k}",
            alpha=0.85,
            x_conversion=days,
        )
        for k in range(5)
    ]
    panel = Axes(
        x=axis("Time", "d", limits=(0.0, 2.05)),
        y=axis("Optical density", None, limits=(0.0, 1.55)),
        legend=Legend(
            visible=True, location="lower right", fontsize=6.5, ncols=2, frame=False
        ),
        grid=True,
        grid_color="0.9",
        artists=plots,
    )
    figure = Figure(name="Growth", width_mm=95, height_mm=65, axes=[panel])
    project = project_of([source], figure)
    fit_to(
        project,
        folder,
        plots[0],
        ExpressionFit(
            expression="K / (1 + exp(-r * (x - t0))) + c",
            parameters=["K", "r", "t0", "c"],
        ),
        initial_values={"K": 1.1, "r": 6.0, "t0": 0.8, "c": 0.02},
        color="0.25",
        linestyle="--",
        label="logistic, replicate 1",
    )
    return project


def calibration(folder: Path) -> Project:
    """A calibration curve with errors on both axes and a quadratic fit with
    residuals, a detection limit as a line and the linear range as a band."""
    rng = np.random.default_rng(107)
    c = np.linspace(0.2, 10.0, 24)  # mg/L
    absorbance = 0.012 + 0.092 * c - 0.0021 * c**2
    absorbance += rng.normal(0.0, 0.01, c.size)
    source = write_csv(
        folder,
        "standards.csv",
        {
            "c": c,
            "dc": np.full(c.size, 0.12),
            "A": absorbance,
            "dA": np.full(c.size, 0.01),
        },
        units=["mg/L", "mg/L", "1", "1"],
        comment="Synthetic calibration standards",
    )
    points = ErrorbarPlot(
        x=column(source, "c"),
        y=column(source, "A"),
        xerr=column(source, "dc"),
        yerr=column(source, "dA"),
        label="standards",
        color="C0",
        marker="o",
        markersize=3.5,
        capsize=1.5,
    )
    panel = Axes(
        x=axis("Concentration", "mg/L", limits=(0.0, 10.5)),
        y=axis("Absorbance", None, limits=(0.0, 0.9)),
        legend=Legend(visible=True, location="upper left"),
        artists=[
            ShadedSpan(
                start=1.0, end=7.0, color="C2", alpha=0.15, label="linear range"
            ),
            ReferenceLine(
                at=0.045,
                orientation="horizontal",
                color="C3",
                linestyle="--",
                label="detection limit",
            ),
            points,
        ],
    )
    figure = Figure(
        name="Calibration",
        width_mm=100,
        height_mm=85,
        layout=GridLayout(rows=1, cols=1),
        axes=[panel],
    )
    project = project_of([source], figure)
    fit_to(
        project,
        folder,
        points,
        PredefinedFit(name="polynomial", degree=2),
        residuals=True,
        color="C1",
        label="quadratic fit",
    )
    return project


def distribution(folder: Path) -> Project:
    """Two samples as overlaid histograms of the density, with a mean and its
    spread drawn as a line and a band."""
    rng = np.random.default_rng(108)
    first = rng.normal(5.0, 1.0, 1500)
    second = rng.normal(6.6, 1.5, 1500)
    source = write_csv(
        folder,
        "samples.csv",
        {"first": first, "second": second},
        units=["mm", "mm"],
        comment="Synthetic sizes of two batches of particles",
    )
    panel = Axes(
        x=axis("Diameter", "mm", limits=(0.0, 12.0)),
        y=axis("Density", "1/mm"),
        legend=Legend(visible=True, location="upper right", frame=False),
        artists=[
            Histogram(
                values=column(source, "first"),
                bins=36,
                density=True,
                color="C0",
                alpha=0.55,
                label="batch A",
            ),
            Histogram(
                values=column(source, "second"),
                bins=36,
                density=True,
                color="C1",
                alpha=0.55,
                label="batch B",
            ),
            ShadedSpan(start=4.0, end=6.0, color="C0", alpha=0.12, label="A: mean ± σ"),
            ReferenceLine(at=5.0, color="C0", linestyle="-", linewidth=1.2),
        ],
    )
    figure = Figure(name="Batches", width_mm=95, height_mm=65, axes=[panel])
    return project_of([source], figure)


def clock_stability(folder: Path) -> Project:
    """The Allan deviation of two series on log-log axes: one given as
    fractional frequency, one as phase, with τ counted in cycles of 2.88 s
    and shown in hours by a formula."""
    rng = np.random.default_rng(109)
    cycles = 93.0 + np.arange(2000.0)
    white = 3.0e-12 * rng.normal(size=cycles.size)  # white frequency noise
    drift = 2.0e-15 * np.arange(cycles.size)  # a slow drift on top
    frequency = white + drift
    phase = np.cumsum(5.0e-12 * rng.normal(size=cycles.size)) * 2.88  # s
    source = write_csv(
        folder,
        "oscillators.csv",
        {"cycle": cycles, "y_a": frequency, "x_b": phase},
        units=["1", "1", "s"],
        comment="Synthetic oscillators, one reading every cycle of 2.88 s",
    )
    hours = Conversion(formula="x * 2.88 / 3600", unit="h")
    a = AllanDeviationPlot(
        values=column(source, "y_a"),
        time=column(source, "cycle"),
        label="oscillator A (fractional frequency)",
        data_type="frequency",
        color="C0",
        x_conversion=hours,
    )
    b = AllanDeviationPlot(
        values=column(source, "x_b"),
        time=column(source, "cycle"),
        label="oscillator B (phase)",
        data_type="phase",
        color="C3",
        marker="s",
        x_conversion=hours,
    )
    panel = Axes(
        x=axis("Averaging time τ", "h", scale="log"),
        y=axis("Allan deviation σ_y(τ)", None, scale="log"),
        legend=Legend(visible=True, location="upper right", frame=False),
        grid=True,
        grid_which="both",
        grid_color="0.9",
        artists=[a, b],
    )
    figure = Figure(name="Stability", width_mm=95, height_mm=70, axes=[panel])
    return project_of([source], figure)


def beam_profile(folder: Path) -> Project:
    """A 2-D map on a logarithmic color scale with its color bar, next to a
    profile through it with a Gaussian fit."""
    rng = np.random.default_rng(110)
    x = np.linspace(-3.0, 3.0, 61)  # mm
    y = np.linspace(-2.0, 2.0, 41)
    gx, gy = np.meshgrid(x, y)
    intensity = np.exp(-(gx**2) / (2 * 0.8**2) - gy**2 / (2 * 0.5**2))
    intensity = 1.0e-3 + intensity * (1.0 + rng.normal(0.0, 0.01, intensity.shape))
    profile = intensity[y.size // 2]
    np.savez(
        folder / "beam.npz",
        intensity=intensity,
        x=x,
        y=y,
        profile=profile,
    )
    grid = numpy_source(folder / "beam.npz", folder, array="intensity")
    xs = numpy_source(folder / "beam.npz", folder, array="x")
    ys = numpy_source(folder / "beam.npz", folder, array="y")
    line = numpy_source(folder / "beam.npz", folder, array="profile")
    mesh = ColorMesh(
        c=ArrayRef(source=grid.id),
        x=column(xs, 0),
        y=column(ys, 0),
        cmap="inferno",
        norm="log",
        vmin=1.0e-3,
        vmax=1.0,
        colorbar=Colorbar(label="Intensity (a.u.)"),
    )
    cut = ScatterPlot(
        x=column(xs, 0),
        y=column(line, 0),
        label="centre line",
        color="C0",
        size=8.0,
    )
    left = Axes(
        col=0,
        x=axis("x", "mm"),
        y=axis("y", "mm"),
        artists=[mesh],
    )
    right = Axes(
        col=1,
        x=axis("x", "mm"),
        y=axis("Profile at y = 0", "a.u."),
        legend=Legend(visible=True, location="upper right", frame=False),
        grid=True,
        grid_color="0.9",
        artists=[cut],
    )
    figure = Figure(
        name="Beam",
        width_mm=170,
        height_mm=62,
        layout=GridLayout(rows=1, cols=2, width_ratios=[1.25, 1.0]),
        panel_labels=PanelLabels(style="(a)"),
        axes=[left, right],
    )
    project = project_of([grid, xs, ys, line], figure)
    fit_to(
        project,
        folder,
        cut,
        PredefinedFit(name="gaussian"),
        color="C3",
        label="Gaussian",
    )
    return project


def paper_figure(folder: Path) -> Project:
    """A journal figure of 175 mm with four panels, shared axes, letters and
    set frame and tick widths; the project has a second figure, the same as a
    single column."""
    rng = np.random.default_rng(111)
    t = np.linspace(0.0, 10.0, 80)
    u = np.exp(-((t - 5.0) ** 2) / 4.0) + rng.normal(0.0, 0.03, t.size)
    v = 0.5 + 0.4 * np.cos(t) * np.exp(-t / 6.0) + rng.normal(0.0, 0.02, t.size)
    p = 2.0 + 3.0 * (t / 10.0) ** 2
    p *= 1.0 + rng.normal(0.0, 0.05, t.size)
    raw_noise = rng.normal(0.0, 1.0, 900)
    filtered_noise = rng.normal(0.0, 0.4, 900)
    source = write_csv(
        folder,
        "results.csv",
        {"t": t, "u": u, "du": np.full(t.size, 0.03), "v": v, "p": p},
        units=["s", "V", "V", "V", "W"],
        comment="Synthetic results for a publication figure",
    )
    noise = write_csv(
        folder,
        "noise.csv",
        {"raw": raw_noise, "filtered": filtered_noise},
        units=["V", "V"],
        comment="Synthetic noise before and after a filter",
    )
    peak = ErrorbarPlot(
        x=column(source, "t"),
        y=column(source, "u"),
        yerr=column(source, "du"),
        label="signal",
        marker="o",
        markersize=2.5,
        capsize=1.0,
        elinewidth=0.6,
    )
    ring = LinePlot(
        x=column(source, "t"),
        y=column(source, "v"),
        label="ringing",
        color="C2",
        linewidth=1.0,
    )
    power = LinePlot(
        x=column(source, "t"),
        y=column(source, "p"),
        label="power",
        color="C1",
        linewidth=1.0,
        axis="right",
    )
    before = Histogram(
        values=column(noise, "raw"), bins=28, density=True, color="C4", alpha=0.75
    )
    after = Histogram(
        values=column(noise, "filtered"),
        bins=28,
        density=True,
        color="C3",
        alpha=0.75,
    )
    top_left = Axes(
        row=0,
        col=0,
        x=axis("Time", "s"),
        y=axis("Voltage", "V"),
        y_right=axis("Power", "W"),
        legend=Legend(visible=True, location="upper left", frame=False, fontsize=6),
        artists=[peak, power],
    )
    top_right = Axes(
        row=0,
        col=1,
        x=axis("Noise before the filter", "V", limits=(-4.0, 4.0)),
        y=axis("Density", "1/V"),
        artists=[before],
    )
    bottom_left = Axes(
        row=1,
        col=0,
        x=axis("Time", "s"),
        y=axis("Voltage", "V"),
        artists=[ring],
    )
    bottom_right = Axes(
        row=1,
        col=1,
        x=axis("Noise after the filter", "V", limits=(-4.0, 4.0)),
        y=axis("Density", "1/V"),
        artists=[after],
    )
    paper = Figure(
        name="Figure 1",
        width_mm=175,
        height_mm=120,
        font_size=8,
        frame_width=0.6,
        tick_width=0.6,
        tick_length=3.0,
        minor_tick_width=0.4,
        layout=GridLayout(rows=2, cols=2, share_x="col"),
        panel_labels=PanelLabels(style="(a)", bold=True),
        axes=[top_left, top_right, bottom_left, bottom_right],
    )
    single = Figure(
        name="Figure 1, single column",
        width_mm=85,
        height_mm=62,
        font_size=8,
        frame_width=0.6,
        tick_width=0.6,
        tick_length=3.0,
        axes=[
            Axes(
                x=axis("Time", "s"),
                y=axis("Voltage", "V"),
                artists=[
                    ErrorbarPlot(
                        x=column(source, "t"),
                        y=column(source, "u"),
                        yerr=column(source, "du"),
                        marker="o",
                        markersize=2.5,
                        capsize=1.0,
                        elinewidth=0.6,
                    )
                ],
            )
        ],
    )
    return project_of([source, noise], paper, single)


def fixed_points(folder: Path) -> Project:
    """A platinum thermometer in baths up to 30 °C and once at the zinc point:
    the x axis is broken between them, the quadratic fit runs across, and the
    residuals share the broken axis."""
    rng = np.random.default_rng(113)
    t = np.array([0.01, 3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 24.0, 27.0, 29.76])
    t = np.append(t, 419.527)  # °C, the freezing point of zinc
    a, b = 3.9083e-3, -5.775e-7  # Callendar-Van Dusen, platinum
    resistance = 25.0 * (1.0 + a * t + b * t**2)
    resistance += rng.normal(0.0, 0.002, t.size)
    source = write_csv(
        folder,
        "pt25.csv",
        {"t": t, "R": resistance, "dR": np.full(t.size, 0.003)},
        units=["°C", "Ω", "Ω"],
        comment="Synthetic calibration of a platinum resistance thermometer",
    )
    points = ErrorbarPlot(
        x=column(source, "t"),
        y=column(source, "R"),
        yerr=column(source, "dR"),
        label="calibration",
        color="C0",
        marker="o",
        markersize=3.5,
        capsize=1.5,
    )
    cut = [(32.0, 416.0)]
    top = Axes(
        x=AxisSpec(breaks=cut),
        y=axis("Resistance $R$", "Ω"),
        legend=Legend(visible=True, location="upper left"),
        artists=[points],
    )
    figure = Figure(
        name="Fixed points",
        width_mm=120,
        height_mm=90,
        layout=GridLayout(rows=1, cols=1),
        axes=[top],
    )
    project = project_of([source], figure)
    fit_to(
        project,
        folder,
        points,
        PredefinedFit(name="polynomial", degree=2),
        residuals=True,
        color="C1",
        label="quadratic fit",
    )
    upper, lower = project.figures[0].axes
    upper.x = AxisSpec(breaks=cut)
    lower.x = axis("Temperature $t$", "°C", breaks=cut)
    lower.y = axis("Residual", "Ω", prefix="m")
    return project


def ir_spectrum(folder: Path) -> Project:
    """An infrared spectrum as a German thesis prints it: wavenumbers from high
    to low, only the left and bottom axis, and a decimal comma."""
    rng = np.random.default_rng(114)
    wavenumber = np.arange(400.0, 4001.0, 4.0)
    transmission = np.full(wavenumber.size, 0.93)
    for centre, depth, width in (
        (3400.0, 0.38, 140.0),  # O-H
        (2950.0, 0.30, 45.0),  # C-H
        (1715.0, 0.72, 22.0),  # C=O
        (1450.0, 0.28, 28.0),
        (1240.0, 0.45, 35.0),
        (1050.0, 0.40, 30.0),
        (720.0, 0.20, 18.0),
    ):
        transmission -= depth * np.exp(-(((wavenumber - centre) / width) ** 2))
    transmission += rng.normal(0.0, 0.004, wavenumber.size)
    source = write_csv(
        folder,
        "spectrum.csv",
        {"k": wavenumber, "T": transmission},
        units=["1/cm", "1"],
        comment="Synthetic infrared spectrum",
    )
    panel = Axes(
        x=axis("Wavenumber", "cm$^{-1}$", limits=(400.0, 4000.0), inverted=True),
        y=axis(
            "Transmission",
            limits=(0.0, 1.0),
            number_format="fixed",
            decimals=1,
        ),
        artists=[
            LinePlot(
                x=column(source, "k"),
                y=column(source, "T"),
                color="black",
                linewidth=0.8,
            ),
            Annotation(
                text="C=O",
                position=(2300.0, 0.17),
                arrow_to=(1725.0, 0.21),
                fontsize=8,
            ),
        ],
    )
    figure = Figure(
        name="IR spectrum",
        width_mm=120,
        height_mm=75,
        open_frame=True,
        decimal_comma=True,
        layout=GridLayout(rows=1, cols=1),
        axes=[panel],
    )
    return project_of([source], figure)


# --- the program --------------------------------------------------------------


def pendulum(folder: Path) -> Project:
    """A spreadsheet as it comes from the lab: three raw times of ten periods
    for each length, and columns the spreadsheet computes from them."""
    rng = np.random.default_rng(112)
    lengths = [round(0.2 + 0.1 * i, 1) for i in range(11)]
    g, reaction = 9.81, 0.12  # m/s², s of scatter of a start and stop by hand
    rows: list[list[object]] = [
        ["Thread pendulum: ten periods timed by hand (synthetic)"],
        [],
        ["L", "t1", "t2", "t3", "T", "T2", "u(T2)", "note"],
        ["m", "s", "s", "s", "s", "s^2", "s^2"],
    ]
    for i, length in enumerate(lengths):
        ten = 20 * np.pi * np.sqrt(length / g)
        times = [round(float(ten + rng.normal(0, reaction)), 2) for _ in range(3)]
        row = len(rows) + 1
        period = sum(times) / 3 / 10
        rows.append(
            [
                length,
                *times,
                Formula(f"AVERAGE(B{row}:D{row})/10", period),
                Formula(f"E{row}*E{row}", period * period),
                Formula(
                    f"2*E{row}*{reaction}/10/SQRT(3)",
                    2 * period * reaction / 10 / 3**0.5,
                ),
                "thread retied" if i == 6 else None,
            ]
        )
    write_ods(folder / "pendulum.ods", {"measurement": rows})
    source = sheet_source(folder / "pendulum.ods", folder, header_row=2, skip_rows=1)
    points = ErrorbarPlot(
        x=column(source, "L"),
        y=column(source, "T2"),
        yerr=column(source, "u(T2)"),
        marker="o",
        linestyle="none",
        markersize=3.5,
        capsize=2.0,
        color="C0",
        label="measured",
    )
    panel = Axes(
        x=axis("Length", "m", limits=(0.0, 1.35)),
        y=axis("Period squared", "s²", limits=(0.0, 5.4)),
        legend=Legend(visible=True, location="upper left", frame=False),
        artists=[points],
    )
    figure = Figure(
        name="Pendulum",
        width_mm=89,
        height_mm=75,
        layout=GridLayout(rows=1, cols=1),
        axes=[panel],
    )
    project = project_of([source], figure)
    fit = fit_to(
        project,
        folder,
        points,
        # Through the origin, as the law says: T^2 = (4 pi^2 / g) L.
        ExpressionFit(expression="a * x", parameters=["a"]),
        color="C1",
        curve_to_limits=True,
        mark_extrapolated=True,
        label="line through the origin",
    )
    slope = fit.result.parameters["a"]
    project.figures[0].axes[0].artists.append(
        Annotation(
            text=f"$g = 4\\pi^2/a$ = {4 * np.pi**2 / slope:.2f} m/s²",
            position=(0.42, 0.07),
            coords="axes",
        )
    )
    return project


EXAMPLES: dict[str, tuple[str, str, str, Callable[[Path], Project] | None]] = {
    # folder: (project file, title, what it shows, builder); a builder of None
    # is an example written by hand, of which only the thumbnail is made.
    "gaussian-scan": (
        "scan.figscribe",
        "A Gaussian scan",
        "A peak with error bars and a Gaussian fit: the place to start.",
        None,
    ),
    "noisy-sensor": (
        "sensor.figscribe",
        "A noisy sensor",
        "A long series as a thin grey line, and on top its means of a minute.",
        noisy_sensor,
    ),
    "rc-discharge": (
        "discharge.figscribe",
        "An RC discharge",
        "An exponential fit with a held offset, its residuals and one glitch.",
        rc_discharge,
    ),
    "freezing-plateau": (
        "furnace.figscribe",
        "A freezing plateau",
        "Hours and °C from s and K, a fixed point, a plateau and a second axis.",
        freezing_plateau,
    ),
    "resonance": (
        "resonator.figscribe",
        "A resonance",
        "Amplitude and phase on a shared log axis with a bounded Lorentzian.",
        resonance,
    ),
    "diode-iv": (
        "diode.figscribe",
        "A diode's current",
        "Many decades on a symmetric log axis, and a fit with your own expression.",
        diode_iv,
    ),
    "growth-curve": (
        "growth.figscribe",
        "A growth curve",
        "Five replicates, hours shown as days, and a logistic fit.",
        growth_curve,
    ),
    "calibration": (
        "standards.figscribe",
        "A calibration",
        "Errors on both axes, a quadratic fit with residuals and a detection limit.",
        calibration,
    ),
    "distribution": (
        "samples.figscribe",
        "Two distributions",
        "Overlaid histograms of the density with a mean and its spread.",
        distribution,
    ),
    "clock-stability": (
        "oscillators.figscribe",
        "Clock stability",
        "The Allan deviation of two series, τ in hours from cycles of 2.88 s.",
        clock_stability,
    ),
    "beam-profile": (
        "beam.figscribe",
        "A beam profile",
        "A map on a log color scale with its bar, and a profile with a Gaussian.",
        beam_profile,
    ),
    "paper-figure": (
        "paper.figscribe",
        "A figure for a paper",
        "175 mm, four panels, shared axes, letters, and a single-column copy.",
        paper_figure,
    ),
    "fixed-points": (
        "thermometer.figscribe",
        "Up to the zinc point",
        "A broken axis to a far point, a fit across it and residuals below.",
        fixed_points,
    ),
    "ir-spectrum": (
        "spectrum.figscribe",
        "An infrared spectrum",
        "Wavenumbers from high to low, an open frame and a decimal comma.",
        ir_spectrum,
    ),
    "pendulum": (
        "pendulum.figscribe",
        "A pendulum from a spreadsheet",
        "A LibreOffice Calc sheet with computed columns, and g from the fit.",
        pendulum,
    ),
}


def thumbnail(figure: Figure, data, path: Path) -> None:
    """The picture of `figure` for the start page: a PNG of the same size for
    every example, so that the tiles line up."""
    dpi = THUMBNAIL_PX / (figure.width_mm / 25.4)
    export(figure.model_copy(update={"dpi": dpi}), data, path)
    with Image.open(path) as image:
        picture = image.convert("RGB")
    picture.thumbnail((THUMBNAIL_PX, THUMBNAIL_HEIGHT_PX))
    canvas = Image.new("RGB", (THUMBNAIL_PX, THUMBNAIL_HEIGHT_PX), "white")
    canvas.paste(
        picture,
        (
            (THUMBNAIL_PX - picture.width) // 2,
            (THUMBNAIL_HEIGHT_PX - picture.height) // 2,
        ),
    )
    canvas.save(path, optimize=True)


def build(name: str, root: Path = HERE) -> Project:
    """Write the example `name` into `root / name` and return its project."""
    project_file, _, _, builder = EXAMPLES[name]
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    if builder is None:
        source = HERE / name  # written by hand: only the thumbnail is made
        project = loads((source / project_file).read_text(encoding="utf-8"))
    else:
        source = folder
        with fixed_ids(sum(map(ord, name))):
            project = builder(folder)
        (folder / project_file).write_text(dumps(project), encoding="utf-8")
    thumbnail(project.figures[0], load_data(project, source), folder / "thumbnail.png")
    return project


def write_index(root: Path = HERE) -> None:
    entries = [
        {"folder": folder, "project": project_file, "title": title, "detail": detail}
        for folder, (project_file, title, detail, _) in EXAMPLES.items()
    ]
    (root / "index.json").write_text(
        json.dumps({"examples": entries}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(names: list[str] | None = None, root: Path = HERE) -> None:
    for name in names or list(EXAMPLES):
        build(name, root)
        print(name)
    write_index(root)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
