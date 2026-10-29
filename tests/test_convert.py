"""Units and a range per plot: the arithmetic every part shares (decision 0041)."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.convert import convert, expression, operation, plot_data, scale
from figscribe.model import ColumnRef, Conversion, ErrorbarPlot, LinePlot

HOURS_SINCE_START = Conversion(factor=1 / 3600, from_start=True, unit="h")


def test_a_whole_inverse_factor_divides_and_any_other_multiplies() -> None:
    assert operation(1 / 3600) == ("/", 3600)
    assert operation(1 / 60) == ("/", 60)
    assert operation(1000.0) == ("*", 1000.0)
    assert operation(2.5) == ("*", 2.5)
    assert operation(1.0) is None  # nothing to compute


def test_values_are_converted_and_can_start_at_zero() -> None:
    t = np.array([7200.0, 3600.0, np.nan, 10800.0])  # unsorted, with a gap
    hours = Conversion(factor=1 / 3600, unit="h")
    assert np.allclose(convert(t, hours), [2, 1, np.nan, 3], equal_nan=True)
    since = convert(t, HOURS_SINCE_START)
    assert np.allclose(since, [1, 0, np.nan, 2], equal_nan=True)
    assert np.array_equal(scale(np.array([360.0]), HOURS_SINCE_START), [0.1])


@pytest.mark.parametrize(
    "conversion",
    [
        HOURS_SINCE_START,
        Conversion(factor=1000.0, unit="ms"),
        Conversion(factor=2.5),
        Conversion(factor=1 / 86400, from_start=True, unit="days"),
    ],
)
def test_the_script_computes_bit_for_bit_what_figscribe_computes(conversion) -> None:
    t = np.linspace(1.7e9, 1.7e9 + 3 * 86400, 1001)  # timestamps in s
    written = eval(expression("t", conversion), {"np": np, "t": t})  # noqa: S307
    assert np.array_equal(written, convert(t, conversion))


def test_the_script_writes_the_conversion_as_a_person_would() -> None:
    assert expression("t", HOURS_SINCE_START) == "(t - np.nanmin(t)) / 3600"
    assert expression("U", Conversion(factor=1000.0)) == "U * 1000"
    assert expression("U", Conversion(factor=1.0, from_start=True)) == (
        "U - np.nanmin(U)"
    )


def test_a_plots_columns_are_converted_and_its_range_kept() -> None:
    columns = {
        "t": [0.0, 3600.0, 7200.0, 10800.0],
        "U": [1.0, 2.0, 3.0, 4.0],
        "dU": [0.1, 0.1, 0.1, 0.1],
    }

    def data(ref):
        return np.asarray(columns[ref.column], dtype=float)

    def ref(column: str) -> ColumnRef:
        return ColumnRef(source="s", column=column)

    plot = ErrorbarPlot(
        x=ref("t"),
        y=ref("U"),
        yerr=ref("dU"),
        x_conversion=Conversion(factor=1 / 3600, unit="h"),
        y_conversion=Conversion(factor=1000.0, unit="mV"),
        x_range=(1.0, 2.0),
    )
    shown = plot_data(plot, data)
    assert list(shown.x) == [0.0, 1.0, 2.0, 3.0]
    assert list(shown.y) == [1000.0, 2000.0, 3000.0, 4000.0]
    assert np.allclose(shown.yerr, 100.0)  # errors scale with their axis
    assert shown.xerr is None
    assert list(shown.used) == [False, True, True, False]  # both ends included

    plain = plot_data(LinePlot(x=ref("t"), y=ref("U")), data)
    assert list(plain.x) == columns["t"] and plain.used.all()
