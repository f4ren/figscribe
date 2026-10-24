"""Numbers as people type them, in every field of the GUI."""

from __future__ import annotations

import re

import pytest
from figscribe.gui.numbers import number, numbers, whole


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1.5", 1.5),
        ("1,5", 1.5),  # decimal comma
        ("−3", -3.0),  # the minus sign that comes with text copied from a PDF
        ("1 000", 1000.0),
        ("1 000,5", 1000.5),  # thin space between thousands
        ("1 000", 1000.0),  # narrow no-break space, as LibreOffice writes it
        ("2e3", 2000.0),
        (" 7 ", 7.0),
    ],
)
def test_numbers_as_people_type_them(text: str, value: float) -> None:
    assert number(text) == value


@pytest.mark.parametrize(
    "text", ["inf", "-inf", "nan", "1e400", "1,000.5", "1,2,3", "abc", ""]
)
def test_what_is_no_usable_number_is_refused_as_typed(text: str) -> None:
    with pytest.raises(ValueError, match=re.escape(repr(text))):
        number(text)


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("0, 0.5, 1", [0.0, 0.5, 1.0]),
        ("0; 0,5; 1", [0.0, 0.5, 1.0]),  # with decimal commas, ; separates
        ("0,5; 1,5", [0.5, 1.5]),
        ("−1; 2", [-1.0, 2.0]),
    ],
)
def test_lists_of_numbers(text: str, values: list[float]) -> None:
    assert numbers(text) == values


def test_whole_numbers() -> None:
    assert whole("1 000") == 1000
    assert whole("−3") == -3
    with pytest.raises(ValueError, match="'1,5' is not a whole number"):
        whole("1,5")
