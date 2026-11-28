"""A refused change leaves the project as it was, also where a rule spans
several fields and pydantic has assigned the value before checking it."""

from __future__ import annotations

import pytest

from figscribe.commands import CommandError, SetField
from figscribe.model import (
    Axes,
    ColumnRef,
    Figure,
    LinePlot,
    Project,
    ShadedSpan,
    Smoothing,
)


@pytest.mark.parametrize(
    ("artist", "path", "value"),
    [
        (ShadedSpan(start=1.0, end=2.0), ("end",), 1.0),
        (
            LinePlot(
                x=ColumnRef(source="s", column=0),
                y=ColumnRef(source="s", column=1),
                smoothing=Smoothing(window=5),
            ),
            ("smoothing", "window"),
            3,
        ),
    ],
    ids=["a range with one end", "a window below its order"],
)
def test_a_refused_change_changes_nothing(artist, path, value) -> None:
    project = Project(figures=[Figure(axes=[Axes(artists=[artist])])])
    before = project.model_dump_json()
    with pytest.raises(CommandError):
        SetField(artist.id, path, value).apply(project)
    assert project.model_dump_json() == before
