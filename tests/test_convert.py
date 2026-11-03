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


# --- a formula for the units (F13, decision 0047) --------------------------------

CELSIUS = Conversion(formula="x - 273.15", unit="°C")
SCALED = Conversion(formula="(x - 32) / 1.8", unit="°C")


def test_values_are_converted_by_the_formula_after_the_start_is_taken() -> None:
    t = np.array([300.0, 273.15, np.nan, 373.15])
    assert np.allclose(convert(t, CELSIUS), [26.85, 0, np.nan, 100], equal_nan=True)
    since = Conversion(formula="x / 60 + 5", from_start=True)
    assert np.allclose(convert(np.array([120.0, 60.0, 240.0]), since), [6, 5, 8])


def test_errors_are_scaled_by_the_formulas_slope_and_never_shifted() -> None:
    assert np.allclose(scale(np.array([1.8, 3.6]), SCALED), [1.0, 2.0])
    assert np.array_equal(scale(np.array([0.5]), CELSIUS), [0.5])  # slope 1


def test_the_old_factor_still_counts_without_a_formula() -> None:
    assert Conversion(factor=2.0, formula=None).formula is None
    assert np.array_equal(convert(np.array([1.0]), Conversion(factor=2.0)), [2.0])


def test_a_formula_that_is_not_linear_is_refused_by_the_model() -> None:
    for bad in ("log(x)", "-x", "x ** 2", "t / 60", "x /"):
        with pytest.raises(ValueError):
            Conversion(formula=bad)


@pytest.mark.parametrize(
    "conversion",
    [
        CELSIUS,
        SCALED,
        Conversion(formula="x / 7.5 - 273.15", unit="K"),
        Conversion(formula="x * 1e3 + 1", from_start=True),
        Conversion(formula="2 * pi * x"),
    ],
)
def test_the_script_computes_the_formula_bit_for_bit(conversion) -> None:
    t = np.linspace(1.7e9, 1.7e9 + 3 * 86400, 1001)
    written = eval(expression("t", conversion), {"np": np, "t": t})  # noqa: S307
    assert np.array_equal(written, convert(t, conversion))


def test_the_script_writes_the_formula_as_typed_with_the_column_for_x() -> None:
    assert expression("T", CELSIUS) == "T - 273.15"
    assert expression("t", Conversion(formula="x / 7.5", from_start=True)) == (
        "(t - np.nanmin(t)) / 7.5"
    )


def test_the_errors_are_written_as_a_division_when_the_slope_is_one_over_a_number() -> (
    None
):
    from figscribe.convert import scale_expression as error_expression

    assert error_expression("dT", Conversion(formula="x / 7.5 - 273.15")) == "dT / 7.5"
    assert error_expression("dT", CELSIUS) == "dT"  # slope 1: nothing to compute
    assert error_expression("dU", Conversion(factor=1 / 3600)) == "dU / 3600"
    assert error_expression("dU", Conversion(factor=0.4)) == "dU * 0.4"  # as before


def test_a_formula_ignores_the_factor_beside_it() -> None:
    both = Conversion(factor=5.0, formula="x - 1")
    assert np.array_equal(convert(np.array([3.0]), both), [2.0])
    assert np.array_equal(scale(np.array([3.0]), both), [3.0])


def test_the_slope_and_offset_are_the_factor_and_zero_without_a_formula() -> None:
    from figscribe.convert import linear

    assert linear(None) == (1.0, 0.0)
    assert linear(Conversion(factor=2.5)) == (2.5, 0.0)
    slope, offset = linear(SCALED)
    assert slope == pytest.approx(1 / 1.8) and offset == pytest.approx(-32 / 1.8)
