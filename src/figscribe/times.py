"""Dates and times in data (decision 0082): what counts as a time, and how it
is read.

Times are `datetime64[us]` from the reader to the plot. A time zone is cut
off, never converted: NumPy alone would turn "12:00+01:00" into 11:00 without
a word. The generated script reads the same way.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import numpy as np

UNIT = "datetime64[us]"
"""One resolution for every file, not the one NumPy would pick from the text."""

ZONE = r"(?<=\d)(Z|[+-]\d\d:?\d\d)$"
"""A time zone at the end of an ISO time, as the script writes it too."""

_ISO = re.compile(
    r"\d{4}-\d\d-\d\d"
    r"([T ]\d\d:\d\d(:\d\d(\.\d+)?)?(Z|[+-]\d\d:?\d\d)?)?"
)


def is_time(text: str) -> bool:
    """Whether `text` is an ISO date, perhaps with a time of day."""
    return parse_times([text]) is not None


def parse_times(texts: Iterable[str]) -> np.ndarray | None:
    """The texts as `datetime64`, NaT for empty ones; None unless every filled
    one is a time and one is filled."""
    cleaned = []
    filled = False
    for text in texts:
        text = text.strip()
        if text:
            if not _ISO.fullmatch(text):
                return None
            filled = True
            text = re.sub(ZONE, "", text) if len(text) > 10 else text
        cleaned.append(text)
    if not filled:
        return None
    try:
        return np.array(cleaned, dtype=UNIT)
    except ValueError:  # such as a thirteenth month
        return None


def needs_trimming(texts: Iterable[str]) -> bool:
    """Whether the times carry blanks or a time zone, which NumPy would misread."""
    return any(
        text != text.strip() or (len(text) > 10 and re.search(ZONE, text))
        for text in texts
    )


def date_text(number: float) -> str:
    """A day number as Matplotlib counts dates, as ISO text, as short as it
    can be written: "2026-11-02", "2026-11-01T22:20". A float of days is
    exact to about a microsecond."""
    total = round(float(number) * 86_400e6)  # microseconds since 1970
    if abs(total - round(total, -3)) <= 2:
        total = round(total, -3)
    stamp = np.datetime64(total, "us")
    for unit, size in (("D", 86_400_000_000), ("m", 60_000_000), ("s", 1_000_000)):
        if total % size == 0:
            return str(np.datetime_as_string(stamp, unit=unit))
    unit = "ms" if total % 1000 == 0 else "us"
    return str(np.datetime_as_string(stamp, unit=unit))
