"""Guessing what columns mean: errors, units and a first plot."""

from __future__ import annotations

import pytest

from figscribe.model import ErrorbarPlot, LinePlot, ScatterPlot
from figscribe.suggest import error_columns, suggest, units_line


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["t", "U", "dU"], {"dU": "U"}),
        (["x", "y", "y_err", "sigma_x"], {"y_err": "y", "sigma_x": "x"}),
        (["T", "ΔT"], {"ΔT": "T"}),
        (["E", "E_unc", "Err_E"], {"E_unc": "E", "Err_E": "E"}),
        (["u", "dU"], {}),  # "dU" is the error of "U", not of "u"
        (["d", "dd"], {"dd": "d"}),
        (["x", "y"], {}),
    ],
)
def test_error_columns_are_found_by_name(names, expected) -> None:
    assert error_columns(names) == expected


@pytest.mark.parametrize(
    ("line", "delimiter", "count", "expected"),
    [
        ("s,V,V", ",", 3, ["s", "V", "V"]),
        ("[s];[V]", ";", 2, ["s", "V"]),
        ("(mm)  (counts)", None, 2, ["mm", "counts"]),
        ("s,,V", ",", 3, ["s", "", "V"]),
        ("0.1,2,3", ",", 3, None),
        ("s,V", ",", 3, None),
        (",,", ",", 3, None),
    ],
)
def test_a_line_of_units(line, delimiter, count, expected) -> None:
    assert units_line(line, delimiter, count) == expected


def test_error_bars_come_first_when_y_has_an_error() -> None:
    found = suggest(["t", "U", "dU"])
    assert [s.kind for s in found] == ["errorbar", "line", "scatter"]
    assert found[0].title == "U ± dU against t"
    assert found[1].title == "U against t" and found[1].detail == "Line"
    artist = found[0].build("src")
    assert isinstance(artist, ErrorbarPlot)
    assert (artist.x.column, artist.y.column, artist.yerr.column) == ("t", "U", "dU")
    assert isinstance(found[1].build("src"), LinePlot)
    assert isinstance(found[2].build("src"), ScatterPlot)


def test_an_error_column_is_never_x_or_y() -> None:
    found = suggest(["dU", "t", "U"])
    assert (found[0].x, found[0].y, found[0].yerr) == ("t", "U", "dU")


def test_numbered_columns_and_too_few_columns() -> None:
    assert [(s.kind, s.x, s.y) for s in suggest([0, 1])] == [
        ("line", 0, 1),
        ("scatter", 0, 1),
    ]
    assert suggest(["t"]) == []
    assert suggest(["U", "dU"]) == []
