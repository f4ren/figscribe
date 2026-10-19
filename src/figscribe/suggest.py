"""What a table of columns probably means: errors, units, a first plot.

Only guesses, offered for the user to accept or change: an error column is
recognised by its name ("dU", "U_err", "sigma_U" next to "U"), a line of
units by its place right below the header, and the first plot takes the
first column as x.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from figscribe.model import ColumnRef, ErrorbarPlot, LinePlot, ScatterPlot

_PREFIXES = (
    "delta_",
    "delta",
    "sigma_",
    "sigma",
    "err_",
    "err",
    "s_",
    "u_",
    "d",
    "Δ",
    "σ",
)
_SUFFIXES = ("_error", "_err", "err", "_unc", "_sigma", "_std", "_sd", "_u")


def error_columns(names: list[str]) -> dict[str, str]:
    """{error column: value column} for every column named as another's error."""
    found: dict[str, str] = {}
    for name in names:
        for value in names:
            if value != name and value not in found and _is_error_of(name, value):
                found[name] = value
                break
    return found


def _is_error_of(name: str, value: str) -> bool:
    lowered = name.lower()
    for prefix in _PREFIXES:
        if not lowered.startswith(prefix.lower()):
            continue
        # "dU" names the error of "U", not of "u"; longer prefixes ignore case.
        if len(prefix) == 1:
            if name[1:] == value:
                return True
        elif lowered[len(prefix) :] == value.lower():
            return True
    return any(
        lowered.endswith(suffix) and lowered[: -len(suffix)] == value.lower()
        for suffix in _SUFFIXES
    )


def units_line(line: str, delimiter: str | None, count: int) -> list[str] | None:
    """The units in `line`, one per column, if it reads as a line of units.

    "s,V,V" and "[s];[V]" are units; a line with a number in it is not.
    """
    fields = line.split() if delimiter is None else line.split(delimiter)
    fields = [f.strip() for f in fields]
    if len(fields) != count or not any(fields):
        return None
    units = [re.sub(r"^[\[(](.*)[\])]$", r"\1", f).strip() for f in fields]
    for unit in units:
        try:
            float(unit.replace(",", "."))
        except ValueError:
            continue
        return None
    return units


@dataclass(frozen=True)
class Suggestion:
    """A first plot of the data: what it is called, and how to build it."""

    kind: str
    """"errorbar", "line" or "scatter"."""
    x: str | int
    y: str | int
    yerr: str | int | None = None

    @property
    def title(self) -> str:
        if self.yerr is not None:
            return f"{self.y} ± {self.yerr} against {self.x}"
        return f"{self.y} against {self.x}"

    @property
    def detail(self) -> str:
        return {"errorbar": "Error bars", "line": "Line", "scatter": "Points"}[
            self.kind
        ]

    def build(self, source_id: str):
        def ref(column: str | int) -> ColumnRef:
            return ColumnRef(source=source_id, column=column)

        if self.kind == "errorbar":
            return ErrorbarPlot(x=ref(self.x), y=ref(self.y), yerr=ref(self.yerr))
        cls = LinePlot if self.kind == "line" else ScatterPlot
        return cls(x=ref(self.x), y=ref(self.y))


def suggest(columns: list[str | int]) -> list[Suggestion]:
    """First plots for these columns, the most likely first.

    x is the first column that is nobody's error, y the next one; with an
    error column for y, error bars come first.
    """
    names = [str(c) for c in columns]
    errors = error_columns(names)
    plain = [c for c, n in zip(columns, names, strict=True) if n not in errors]
    if len(plain) < 2:
        return []
    x, y = plain[0], plain[1]
    yerr = next(
        (c for c, n in zip(columns, names, strict=True) if errors.get(n) == str(y)),
        None,
    )
    found = []
    if yerr is not None:
        found.append(Suggestion("errorbar", x, y, yerr))
    found += [Suggestion("line", x, y), Suggestion("scatter", x, y)]
    return found
