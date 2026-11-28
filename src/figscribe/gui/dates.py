"""Dates in the window (decision 0082): where the numbers of the model are
dates, and how they are shown and typed there."""

from __future__ import annotations

from matplotlib.dates import date2num

from figscribe.model import Annotation, Project, ReferenceLine, ShadedSpan
from figscribe.model.timeaxes import as_dates, date_axis, time_columns_of
from figscribe.times import date_text, parse_times

EXAMPLE = "2026-11-01 12:30"


def date_label(number: float) -> str:
    """A place on a date axis as it is shown: "2026-11-01 12:30", to a
    millisecond at most: a dragged note lies anywhere."""
    milliseconds = round(number * 86_400_000)
    return date_text(milliseconds / 86_400_000).replace("T", " ")


def date_number(text: str) -> float:
    """A typed date as days since 1970; a ValueError that says what to type."""
    values = parse_times([text])
    if values is None:
        raise ValueError(f"{text.strip()!r} is no date; type it as {EXAMPLE}")
    return float(date2num(values[0]))


def date_pair(text: str, dated: tuple[bool, bool], number) -> tuple[float, float]:
    """The position of a note as typed, "date, 20.5", or with a semicolon for
    a decimal comma; `number` reads the part that is no date."""
    parts = text.split(";" if ";" in text else ",")
    if len(parts) != 2:
        raise ValueError(f"needs two values, such as {EXAMPLE}, 20.5")
    x, y = (
        date_number(part) if on_dates else number(part)
        for part, on_dates in zip(parts, dated, strict=True)
    )
    return x, y


def axis_on_dates(project: Project, axes_id: str, field: str) -> bool:
    """Whether the `field` axis of the panel shows dates."""
    for figure in project.figures:
        for i, axes in enumerate(figure.axes):
            if axes.id == axes_id and getattr(axes, field) is not None:
                return date_axis(figure, i, field, time_columns_of(project))
    return False


def places_on_dates(project: Project, obj) -> tuple[bool, bool]:
    """Whether places of `obj` along x and along y are dates: of a reference
    line or range, a note placed on the data, or a plot's own range."""
    for figure in project.figures:
        for axes in figure.axes:
            if not any(a.id == obj.id for a in axes.artists):
                continue
            right = obj.axis == "right" and axes.y_right is not None
            if isinstance(obj, Annotation) and obj.coords != "data":
                return False, False
            if isinstance(obj, Annotation | ReferenceLine | ShadedSpan):
                x = axis_on_dates(project, axes.id, "x")
                y = axis_on_dates(project, axes.id, "y_right" if right else "y")
                if isinstance(obj, ReferenceLine | ShadedSpan):
                    upright = obj.orientation == "vertical"
                    return (x and upright, y and not upright)
                return x, y
            if "x_range" in type(obj).model_fields and "y" in type(obj).model_fields:
                return as_dates(obj, "x", time_columns_of(project)), False
    return False, False
