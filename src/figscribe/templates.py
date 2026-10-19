"""Layouts to start a figure from, at the sizes journals and slides ask for.

A template only builds a Figure: size, panel grid and empty panels. The data
and plots come afterwards, so every template works with any data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from figscribe.model import Axes, Figure, GridLayout


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    detail: str
    build: Callable[[], Figure]


def _single() -> Figure:
    return Figure(name="Figure 1", width_mm=85, height_mm=60, axes=[Axes()])


def _double() -> Figure:
    return Figure(name="Figure 1", width_mm=175, height_mm=70, axes=[Axes()])


def _residuals() -> Figure:
    return Figure(
        name="Figure 1",
        width_mm=85,
        height_mm=80,
        layout=GridLayout(rows=2, share_x="col", height_ratios=[3, 1]),
        axes=[Axes(row=0), Axes(row=1)],
    )


def _side_by_side() -> Figure:
    return Figure(
        name="Figure 1",
        width_mm=175,
        height_mm=80,
        layout=GridLayout(cols=2),
        axes=[Axes(col=0), Axes(col=1)],
    )


def _slide() -> Figure:
    return Figure(
        name="Figure 1",
        width_mm=254,
        height_mm=143,
        dpi=200,
        stylesheet="seaborn-v0_8-talk",
        axes=[Axes()],
    )


TEMPLATES = [
    Template("single", "Single column", "85 × 60 mm", _single),
    Template("double", "Double column", "175 × 70 mm", _double),
    Template(
        "residuals", "Data, fit and residuals", "85 × 80 mm · 2 panels", _residuals
    ),
    Template("side-by-side", "Side by side", "175 × 80 mm · 2 panels", _side_by_side),
    Template("slide", "Slide 16:9", "254 × 143 mm · large type", _slide),
]


def template(key: str) -> Template:
    for candidate in TEMPLATES:
        if candidate.key == key:
            return candidate
    raise KeyError(f"no template {key!r}")
