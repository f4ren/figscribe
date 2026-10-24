"""Style strings: what Matplotlib accepts passes, the rest is said plainly."""

from __future__ import annotations

import pytest
from figscribe.model.styles import style_problem, style_problems

from figscribe.model import Axes, Legend


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("color", "C0"),
        ("color", "tab:blue"),
        ("color", "#ff0000"),
        ("color", "0.5"),
        ("edgecolor", "none"),
        ("marker", "$x$"),
        ("marker", None),
        ("linestyle", "none"),
        ("linestyle", "dashed"),
        ("cmap", "magma"),
        ("location", "upper left"),
        ("label", "anything at all"),  # not a style field
    ],
)
def test_what_matplotlib_accepts_passes(name: str, value) -> None:
    assert style_problem(name, value) is None


@pytest.mark.parametrize(
    ("name", "value", "said"),
    [
        ("color", "blu", "is not a color"),
        ("grid_color", "dark", "is not a color"),
        ("marker", "q", "is not a marker"),
        ("linestyle", "..", "is not a line style"),
        ("cmap", "viridiss", "is not a color map"),
        ("location", "top", "is not a legend location"),
    ],
)
def test_what_matplotlib_refuses_is_said_plainly(
    name: str, value: str, said: str
) -> None:
    assert style_problem(name, value).startswith(f"{value!r} {said}")


def test_style_strings_in_nested_parts_are_found() -> None:
    axes = Axes(legend=Legend(location="top"), grid_color="dark")
    assert {path for path, _ in style_problems(axes)} == {
        "legend.location",
        "grid_color",
    }
