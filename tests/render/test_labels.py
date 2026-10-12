"""How an axis label and its unit are joined."""

from __future__ import annotations

import pytest

from figscribe.model import AxisSpec
from figscribe.render import axis_label


@pytest.mark.parametrize(
    ("unit_format", "expected"),
    [
        ("slash", "$U$ / V"),
        ("parentheses", "$U$ (V)"),
        ("brackets", "$U$ [V]"),
    ],
)
def test_unit_formats(unit_format: str, expected: str) -> None:
    assert axis_label(AxisSpec(label="$U$", unit="V"), unit_format) == expected


def test_compound_unit_is_parenthesised_after_a_slash() -> None:
    # "v / m/s" would read as v divided by m divided by s.
    spec = AxisSpec(label="$v$", unit="m/s")
    assert axis_label(spec, "slash") == "$v$ / (m/s)"
    assert axis_label(spec, "parentheses") == "$v$ (m/s)"


def test_label_without_unit_is_left_alone() -> None:
    assert axis_label(AxisSpec(label="counts"), "slash") == "counts"


def test_no_label_means_no_label_even_with_a_unit() -> None:
    assert axis_label(AxisSpec(unit="V"), "slash") is None


def test_parentheses_are_the_default() -> None:
    from figscribe.model import Figure

    assert Figure().unit_format == "parentheses"


def test_unit_is_set_as_text_so_it_stays_upright() -> None:
    # The quantity symbol is italic because the user writes it as math; the
    # unit must not be pulled into math mode, where it would turn italic too.
    label = axis_label(AxisSpec(label="$U$", unit="mV"), "parentheses")
    assert label == "$U$ (mV)"
    assert label.count("$") == 2
