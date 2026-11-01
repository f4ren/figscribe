"""Fewer points drawn: groups of rows averaged or thinned (decision 0045)."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.convert import plot_data
from figscribe.fit import FitError
from figscribe.model import (
    ColumnRef,
    Conversion,
    ErrorbarPlot,
    LinePlot,
    Reduction,
    ScatterPlot,
)


def provider(**columns):
    def data(ref):
        return np.asarray(columns[ref.column], dtype=float)

    return data


def ref(column: str) -> ColumnRef:
    return ColumnRef(source="s", column=column)


def line(data, **options):
    x = np.arange(100.0)
    columns = {"t": x, "U": 2 * x + np.sin(x), **data}
    reduction = Reduction(**options.pop("reduction"))
    plot = LinePlot(x=ref("t"), y=ref("U"), reduction=reduction, **options)
    return plot_data(plot, provider(**columns)), columns


def test_a_mean_of_ten_rows_has_the_standard_error_as_its_error() -> None:
    shown, columns = line({}, reduction={"method": "mean", "count": 10})
    groups = columns["U"].reshape(10, 10)
    assert shown.reduced and len(shown.x) == 10
    assert np.allclose(shown.x, columns["t"].reshape(10, 10).mean(axis=1))
    assert np.allclose(shown.y, groups.mean(axis=1))
    assert np.allclose(shown.yerr, groups.std(axis=1, ddof=1) / np.sqrt(10))
    assert shown.xerr is None
    assert shown.used.all()
    assert np.array_equal(shown.rows, np.arange(0, 100, 10))


def test_the_median_has_no_error() -> None:
    shown, columns = line({}, reduction={"method": "median", "count": 10})
    assert np.allclose(shown.y, np.median(columns["U"].reshape(10, 10), axis=1))
    assert shown.yerr is None


def test_every_nth_row_is_taken_as_it_is() -> None:
    shown, columns = line({}, reduction={"method": "every", "count": 25})
    assert list(shown.x) == [0, 25, 50, 75]
    assert np.array_equal(shown.y, columns["U"][::25])
    assert shown.yerr is None


def test_the_mean_over_x_intervals_groups_by_where_a_row_lies() -> None:
    x = np.array([0.0, 0.5, 1.0, 5.0, 5.5, 9.9])
    plot = LinePlot(
        x=ref("t"),
        y=ref("U"),
        reduction=Reduction(method="interval", width=2.0),
    )
    shown = plot_data(plot, provider(t=x, U=x * 10))
    assert np.allclose(shown.x, [0.5, 5.25, 9.9])  # three intervals hold a row
    assert np.allclose(shown.y, [5.0, 52.5, 99.0])
    assert np.isnan(shown.yerr[2])  # one row, no error column: none


def test_the_incomplete_last_group_is_kept_or_dropped() -> None:
    x = np.arange(25.0)
    cases = {True: 3, False: 2}
    for keep, groups in cases.items():
        plot = LinePlot(
            x=ref("t"),
            y=ref("U"),
            reduction=Reduction(count=10, keep_last=keep),
        )
        shown = plot_data(plot, provider(t=x, U=x))
        assert len(shown.x) == groups
    assert shown.x[-1] == 14.5
    kept = plot_data(
        LinePlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10)),
        provider(t=x, U=x),
    )
    assert kept.x[-1] == 22.0  # rows 21 to 25, averaged over the five it has
    assert kept.yerr[-1] == pytest.approx(np.std(x[20:], ddof=1) / np.sqrt(5))


def test_a_group_of_one_row_has_no_error_and_never_a_zero() -> None:
    x = np.arange(21.0)  # the last group is row 21 alone
    alike = np.ones(21)
    plot = LinePlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    shown = plot_data(plot, provider(t=x, U=alike))
    assert np.isnan(shown.yerr).all()  # all alike: an error of 0 is none
    shown = plot_data(plot, provider(t=x, U=x**2))
    assert np.isnan(shown.yerr[-1]) and np.isfinite(shown.yerr[:-1]).all()


def test_an_error_column_is_propagated() -> None:
    x = np.arange(20.0)
    sigma = np.linspace(0.1, 0.5, 20)
    plot = ErrorbarPlot(
        x=ref("t"), y=ref("U"), yerr=ref("dU"), reduction=Reduction(count=10)
    )
    shown = plot_data(plot, provider(t=x, U=x, dU=sigma))
    expected = np.sqrt((sigma.reshape(2, 10) ** 2).sum(axis=1)) / 10
    assert np.allclose(shown.yerr, expected)


def test_x_errors_are_propagated_too_and_the_median_drops_them() -> None:
    x = np.arange(20.0)
    sigma = np.full(20, 0.2)
    for method, expected in (("mean", 0.2 / np.sqrt(10)), ("median", None)):
        plot = ErrorbarPlot(
            x=ref("t"),
            y=ref("U"),
            xerr=ref("dt"),
            reduction=Reduction(method=method, count=10),
        )
        shown = plot_data(plot, provider(t=x, U=x, dt=sigma))
        if expected is None:
            assert shown.xerr is None
        else:
            assert np.allclose(shown.xerr, expected)


def test_a_row_left_out_is_removed_and_the_groups_after_it_do_not_shift() -> None:
    shown, columns = line({}, reduction={"count": 10}, left_out=[57])
    y = columns["U"]
    assert len(shown.x) == 10
    nine = np.delete(y[50:60], 7)
    assert shown.y[5] == pytest.approx(nine.mean())
    assert shown.yerr[5] == pytest.approx(nine.std(ddof=1) / np.sqrt(9))
    assert shown.y[6] == pytest.approx(y[60:70].mean())  # the next group is the same
    assert shown.rows is not None and shown.rows[6] == 60
    # the arrays are the reduced ones: nothing indexes them by file row
    assert shown.rows_kept([57]).all()


def test_a_left_out_row_can_be_replaced_by_the_mean_of_its_neighbours() -> None:
    options = {"count": 10, "replace_left_out": True}
    shown, columns = line({}, reduction=options, left_out=[57])
    y = columns["U"]
    group = y[50:60].copy()
    group[7] = (y[56] + y[58]) / 2
    assert shown.y[5] == pytest.approx(group.mean())  # over all ten values
    measured = np.delete(y[50:60], 7)  # the error counts the nine measured
    assert shown.yerr[5] == pytest.approx(measured.std(ddof=1) / np.sqrt(9))


def test_a_replaced_row_at_the_start_takes_its_one_neighbour() -> None:
    options = {"count": 10, "replace_left_out": True}
    shown, columns = line({}, reduction=options, left_out=[0])
    y = columns["U"]
    group = y[:10].copy()
    group[0] = y[1]
    assert shown.y[0] == pytest.approx(group.mean())


def test_a_propagated_error_counts_the_measured_rows_only() -> None:
    x = np.arange(10.0)
    sigma = np.full(10, 0.3)
    plot = ErrorbarPlot(
        x=ref("t"),
        y=ref("U"),
        yerr=ref("dU"),
        left_out=[4],
        reduction=Reduction(count=10, replace_left_out=True),
    )
    shown = plot_data(plot, provider(t=x, U=x, dU=sigma))
    assert shown.yerr[0] == pytest.approx(np.sqrt(9 * 0.3**2) / 9)


def test_every_nth_with_its_row_replaced_has_no_error_for_it() -> None:
    x = np.arange(30.0)
    plot = ErrorbarPlot(
        x=ref("t"),
        y=ref("U"),
        yerr=ref("dU"),
        left_out=[10],
        reduction=Reduction(method="every", count=10, replace_left_out=True),
    )
    shown = plot_data(plot, provider(t=x, U=x * x, dU=np.ones(30)))
    assert list(shown.x) == [0, 10, 20]
    assert shown.y[1] == (81 + 121) / 2
    assert np.isnan(shown.yerr[1]) and shown.yerr[0] == 1.0


def test_the_range_and_the_conversion_come_before_the_groups() -> None:
    plot = LinePlot(
        x=ref("t"),
        y=ref("U"),
        x_conversion=Conversion(factor=0.1),
        x_range=(1.0, 4.9),
        reduction=Reduction(count=10),
    )
    x = np.arange(100.0)
    shown = plot_data(plot, provider(t=x, U=x))
    # shown x 1.0 to 4.9 is rows 10 to 49: four groups, the same as the file's
    assert len(shown.x) == 4
    assert np.allclose(shown.x, [1.45, 2.45, 3.45, 4.45])


def test_non_finite_rows_are_removed() -> None:
    x = np.arange(20.0)
    y = x.copy()
    y[3] = np.nan
    plot = LinePlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    shown = plot_data(plot, provider(t=x, U=y))
    assert shown.y[0] == pytest.approx(np.delete(y[:10], 3).mean())
    assert np.isfinite(shown.y).all()


def test_points_plots_are_reduced_like_lines() -> None:
    plot = ScatterPlot(x=ref("t"), y=ref("U"), reduction=Reduction(count=10))
    x = np.arange(30.0)
    shown = plot_data(plot, provider(t=x, U=x))
    assert len(shown.x) == 3 and shown.yerr is not None


def test_a_row_left_out_beyond_the_data_is_an_error_as_before() -> None:
    plot = LinePlot(
        x=ref("t"), y=ref("U"), left_out=[500], reduction=Reduction(count=10)
    )
    x = np.arange(100.0)
    with pytest.raises(FitError, match="row 501 is left out"):
        plot_data(plot, provider(t=x, U=x))


def test_an_unreduced_plot_is_as_before() -> None:
    plot = LinePlot(x=ref("t"), y=ref("U"), left_out=[2])
    shown = plot_data(plot, provider(t=np.arange(5.0), U=np.arange(5.0)))
    assert not shown.reduced and shown.rows is None
    assert list(shown.rows_kept([2])) == [True, True, False, True, True]
