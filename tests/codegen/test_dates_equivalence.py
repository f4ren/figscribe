"""Date axes: the script draws what the preview draws (decision 0082)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
import pytest
from matplotlib.dates import date2num

from figscribe.io.csvfile import csv_source
from figscribe.io.hdf5file import hdf5_source
from figscribe.io.numpyfile import numpy_source
from figscribe.io.sheetfile import sheet_source
from figscribe.model import (
    AllanDeviationPlot,
    Annotation,
    Axes,
    AxisSpec,
    ColumnRef,
    Conversion,
    ErrorBand,
    ErrorbarPlot,
    Figure,
    GridLayout,
    Histogram,
    Legend,
    LinePlot,
    Project,
    ReferenceLine,
    ScatterPlot,
    ShadedSpan,
)
from tests.codegen.test_equivalence import _assert_same
from tests.hdf5files import write_h5
from tests.sheetfiles import write_ods, write_xlsx
from tests.timedata import log_file

HOUR = Conversion(factor=1 / 3600, from_start=True, unit="h")


def _day(text: str) -> float:
    return float(date2num(np.datetime64(text)))


def _project(source, *panels, **figure) -> Project:
    return Project(
        figscribe_version="test",
        sources=[source],
        figures=[Figure(axes=list(panels), **figure)],
    )


def _log(folder: Path, **options):
    source = csv_source(log_file(folder, **options), folder)

    def ref(column: str) -> ColumnRef:
        return ColumnRef(source=source.id, column=column)

    return source, ref


@pytest.mark.parametrize("zone", ["", "+01:00"])
def test_a_date_axis_from_a_csv(tmp_path: Path, zone: str) -> None:
    source, ref = _log(tmp_path, zone=zone)
    panel = Axes(
        artists=[
            LinePlot(x=ref("time"), y=ref("T"), label="T"),
            ReferenceLine(orientation="vertical", at=_day("2026-11-02")),
            ShadedSpan(
                orientation="vertical",
                start=_day("2026-11-01T23:00"),
                end=_day("2026-11-01T23:30"),
            ),
            Annotation(text="midnight", position=(_day("2026-11-02"), 20.0)),
            Annotation(
                text="here",
                position=(_day("2026-11-02T00:30"), 20.5),
                arrow_to=(_day("2026-11-02T01:00"), 19.5),
            ),
        ],
        legend=Legend(),
    )
    script = _assert_same(_project(source, panel), tmp_path)
    assert 'dtype="datetime64[us]"' in script or "re.sub" in script
    assert ("re.sub" in script) == bool(zone)
    assert 'np.datetime64("2026-11-02")' in script
    assert "ax.xaxis" in script and "date_ticks(" in script


def test_limits_ticks_range_and_style(tmp_path: Path) -> None:
    source, ref = _log(tmp_path)
    ends = (_day("2026-11-01T22:30"), _day("2026-11-02T01:30"))
    first = Axes(
        artists=[ErrorbarPlot(x=ref("time"), y=ref("T"), yerr=ref("dT"), x_range=ends)],
        x=AxisSpec(limits=(_day("2026-11-01T22:00"), _day("2026-11-02T02:00"))),
    )
    second = Axes(
        row=1,
        artists=[ScatterPlot(x=ref("time"), y=ref("p"))],
        x=AxisSpec(
            ticks=[_day("2026-11-01T23:00"), _day("2026-11-02T01:00")],
            tick_size=6,
            minor_ticks=False,
        ),
    )
    project = _project(
        source,
        first,
        second,
        layout=GridLayout(rows=2, cols=1),
        stylesheet="ggplot",
    )
    _assert_same(project, tmp_path)


def test_shared_date_axes_and_a_right_axis(tmp_path: Path) -> None:
    source, ref = _log(tmp_path, step=3600 * 7)
    first = Axes(artists=[LinePlot(x=ref("time"), y=ref("T"))])
    second = Axes(
        row=1,
        y_right=AxisSpec(),
        artists=[
            LinePlot(x=ref("time"), y=ref("p")),
            LinePlot(
                x=ref("time"),
                y=ref("T"),
                axis="right",
                color="C1",
            ),
        ],
    )
    layout = GridLayout(rows=2, cols=1, share_x="col")
    project = _project(source, first, second, layout=layout)
    _assert_same(project, tmp_path)


def test_dates_on_the_y_axis_and_a_band(tmp_path: Path) -> None:
    source, ref = _log(tmp_path)
    panel = Axes(artists=[LinePlot(x=ref("T"), y=ref("time"))])
    other = Axes(
        col=1,
        artists=[
            ErrorbarPlot(x=ref("time"), y=ref("T"), yerr=ref("dT"), band=ErrorBand())
        ],
    )
    project = _project(source, panel, other, layout=GridLayout(rows=1, cols=2))
    _assert_same(project, tmp_path)


@pytest.mark.parametrize(
    "conversion",
    [
        HOUR,
        Conversion(factor=1.0, from_start=True, unit="s"),
        Conversion(factor=1 / 60, from_start=True, unit="min"),
        Conversion(factor=1 / 86400, from_start=True, unit="d"),
        Conversion(factor=0.25, from_start=True, unit="x"),
        Conversion(formula="x / 3600 + 1", from_start=True, unit="h"),
    ],
    ids=["h", "s", "min", "d", "factor", "formula"],
)
def test_time_since_the_start(tmp_path: Path, conversion: Conversion) -> None:
    source, ref = _log(tmp_path)
    line = LinePlot(x=ref("time"), y=ref("T"), x_conversion=conversion)
    script = _assert_same(_project(source, Axes(artists=[line])), tmp_path)
    assert "np.timedelta64" in script and "date_ticks" not in script


def test_what_is_not_drawn_is_said_in_the_script(tmp_path: Path) -> None:
    source, ref = _log(tmp_path)
    panel = Axes(
        artists=[
            LinePlot(x=ref("time"), y=ref("T")),
            LinePlot(x=ref("p"), y=ref("T"), label="numbers"),
            Histogram(values=ref("time")),
        ],
        x=AxisSpec(scale="log"),
    )
    script = _assert_same(_project(source, panel), tmp_path)
    assert "# numbers is not drawn: its x are numbers" in script
    assert "set_xscale" not in script


def test_gaps_in_the_times(tmp_path: Path) -> None:
    path = tmp_path / "gaps.csv"
    path.write_text(
        "time,T\n2026-11-01 22:00,1\n,2\n2026-11-01 23:00,3\n2026-11-02,4\n"
    )
    source = csv_source(path, tmp_path)
    line = LinePlot(
        x=ColumnRef(source=source.id, column="time"),
        y=ColumnRef(source=source.id, column="T"),
        marker="o",
    )
    _assert_same(_project(source, Axes(artists=[line])), tmp_path)


def _stamps(count: int = 12) -> list[datetime]:
    return [datetime(2026, 11, 1, 10 + i % 12, 5 * i % 60) for i in range(count)]


@pytest.mark.parametrize("write", [write_xlsx, write_ods])
def test_dates_of_a_spreadsheet(tmp_path: Path, write) -> None:
    path = tmp_path / ("log.ods" if write is write_ods else "log.xlsx")
    rows = [["time", "T"]] + [[s, float(i)] for i, s in enumerate(_stamps())]
    write(path, {"s": rows})
    source = sheet_source(path, tmp_path)
    line = LinePlot(
        x=ColumnRef(source=source.id, column="time"),
        y=ColumnRef(source=source.id, column="T"),
    )
    script = _assert_same(_project(source, Axes(artists=[line])), tmp_path)
    assert "sheet_times(" in script


@pytest.mark.parametrize("kind", ["npy", "npz"])
def test_dates_of_numpy(tmp_path: Path, kind: str) -> None:
    stamps = np.array(_stamps(), dtype="datetime64[s]")
    path = tmp_path / f"t.{kind}"
    if kind == "npz":
        np.savez(path, t=stamps, y=np.arange(12.0))
    else:
        np.save(path, stamps)
    times = numpy_source(path, tmp_path)
    np.save(tmp_path / "y.npy", np.arange(12.0))
    values = numpy_source(tmp_path / "y.npy", tmp_path)
    line = LinePlot(
        x=ColumnRef(source=times.id, column=0),
        y=ColumnRef(source=values.id, column=0),
    )
    project = Project(
        figscribe_version="test",
        sources=[times, values],
        figures=[Figure(axes=[Axes(artists=[line])])],
    )
    script = _assert_same(project, tmp_path)
    assert 'astype("datetime64[us]")' in script


@pytest.mark.parametrize("holds", ["group", "table"])
def test_dates_of_hdf5(tmp_path: Path, holds: str) -> None:
    stamps = np.array(_stamps(), dtype="datetime64[us]")
    text = np.array([f"{s}+01:00".encode() for s in stamps])
    path = tmp_path / "log.h5"
    if holds == "table":
        records = np.zeros(12, dtype=[("time", text.dtype), ("T", "f8")])
        records["time"], records["T"] = text, np.arange(12.0)
        write_h5(path, {"run": records})
        names = ["time"]
    else:
        opaque = stamps.astype(h5py.opaque_dtype(stamps.dtype))
        write_h5(path, {"run/time": text, "run/stamp": opaque, "run/T": range(12)})
        names = ["time", "stamp"]
    source = hdf5_source(path, tmp_path)
    artists = [
        LinePlot(
            x=ColumnRef(source=source.id, column=name),
            y=ColumnRef(source=source.id, column="T"),
        )
        for name in names
    ]
    script = _assert_same(_project(source, Axes(artists=artists)), tmp_path)
    assert "iso_times(" in script


def test_an_allan_deviation_with_a_column_of_times(tmp_path: Path) -> None:
    source, ref = _log(tmp_path, step=60, count=60)
    allan = AllanDeviationPlot(values=ref("T"), time=ref("time"), x_range=(0.0, 1800.0))
    script = _assert_same(_project(source, Axes(artists=[allan])), tmp_path)
    assert "np.timedelta64" in script


def test_the_window_may_speak_german(tmp_path: Path, qapp) -> None:
    """Qt sets the system's language for the process; numbers only keeps the
    preview as the script draws it."""
    import locale

    before = locale.setlocale(locale.LC_TIME)
    try:
        for name in ("de_DE.UTF-8", "de_DE.utf8"):
            try:
                locale.setlocale(locale.LC_TIME, name)
                break
            except locale.Error:
                continue
        else:
            pytest.skip("no German locale on this system")
        source, ref = _log(tmp_path, step=86400 * 3)
        line = LinePlot(x=ref("time"), y=ref("T"))
        _assert_same(_project(source, Axes(artists=[line])), tmp_path)
    finally:
        locale.setlocale(locale.LC_TIME, before)
