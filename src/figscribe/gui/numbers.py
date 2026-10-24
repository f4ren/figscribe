"""Numbers as people type them, for every field of the GUI.

A comma is a decimal mark: as a thousands separator too, "1,500" would mean
two different things. Thousands are grouped with spaces instead, as SI and
ISO 80000 write them. The minus sign (−) that comes with text copied from a
PDF is a minus. Lists are separated by ";" as soon as one appears, so that
their numbers can have decimal commas, and by "," otherwise.
"""

from __future__ import annotations

import math
import re

MINUS = "−"

_THOUSANDS = re.compile(r"(?<=\d)[    ](?=\d{3}(?!\d))")
"""A space, no-break space or thin space between groups of three digits. Any
other space stays, so that "0.5 1" (a list missing its comma) is refused
rather than read as 0.51."""


def number(text: str) -> float:
    """`text` as a finite number; a ValueError quoting `text` if it is none."""
    plain = _plain(text)
    if plain.count(",") == 1 and "." not in plain:
        plain = plain.replace(",", ".")
    try:
        value = float(plain)
    except ValueError:
        raise ValueError(f"{text!r} is not a number") from None
    if not math.isfinite(value):
        raise ValueError(f"{text!r} is not a finite number")
    return value


def whole(text: str) -> int:
    try:
        return int(_plain(text))
    except ValueError:
        raise ValueError(f"{text!r} is not a whole number") from None


def numbers(text: str) -> list[float]:
    """A list of numbers, separated by ";" if there is one, else by ","."""
    return [number(part) for part in text.split(";" if ";" in text else ",")]


def _plain(text: str) -> str:
    return _THOUSANDS.sub("", text.strip().replace(MINUS, "-"))
