"""Adding panels beside or inside others, and removing them with their insets."""

from __future__ import annotations

import pytest

from figscribe.commands import CommandError, History, add_panel, remove_axes
from figscribe.model import (
    Axes,
    Figure,
    GridLayout,
    Inset,
    Project,
    validate_references,
)


def _project(*axes: Axes, rows: int = 1, cols: int = 1, **layout) -> Project:
    figure = Figure(layout=GridLayout(rows=rows, cols=cols, **layout), axes=list(axes))
    return Project(figures=[figure])


def _apply(project: Project, axes_id: str, side: str) -> tuple[History, Axes]:
    history = History(project)
    command, new = add_panel(project, axes_id, side)
    history.push(command)
    return history, new


def _cells(project: Project) -> dict[str, tuple[int, int, int, int]]:
    return {
        a.id: (a.row, a.col, a.rowspan, a.colspan)
        for a in project.figures[0].axes
        if a.inset is None
    }


@pytest.mark.parametrize(
    ("side", "layout", "old", "new"),
    [
        ("right", (1, 2), (0, 0, 1, 1), (0, 1, 1, 1)),
        ("left", (1, 2), (0, 1, 1, 1), (0, 0, 1, 1)),
        ("above", (2, 1), (1, 0, 1, 1), (0, 0, 1, 1)),
        ("below", (2, 1), (0, 0, 1, 1), (1, 0, 1, 1)),
    ],
)
def test_a_panel_grows_the_grid(side, layout, old, new) -> None:
    axes = Axes()
    project = _project(axes)
    history, added = _apply(project, axes.id, side)
    figure = project.figures[0]
    assert (figure.layout.rows, figure.layout.cols) == layout
    assert _cells(project)[axes.id] == old
    assert _cells(project)[added.id] == new
    assert validate_references(project) == []
    where = {"right": "to the right", "left": "to the left"}.get(side, side)
    assert history.undo_text == f"Add panel {where}"
    history.undo()
    assert (figure.layout.rows, figure.layout.cols) == (1, 1)
    assert _cells(project) == {axes.id: (0, 0, 1, 1)}


def test_a_free_cell_is_used_first() -> None:
    top, bottom = Axes(row=0, col=0), Axes(row=1, col=0)
    project = _project(top, bottom, rows=2, cols=2)
    _, added = _apply(project, bottom.id, "right")
    assert project.figures[0].layout.cols == 2
    assert _cells(project)[added.id] == (1, 1, 1, 1)


def test_inserting_moves_and_stretches_the_others() -> None:
    left, right = Axes(col=0), Axes(col=1)
    wide = Axes(row=1, col=0, colspan=2)
    project = _project(left, right, wide, rows=2, cols=2, width_ratios=[2.0, 1.0])
    _, added = _apply(project, left.id, "right")
    layout = project.figures[0].layout
    assert layout.cols == 3 and layout.width_ratios == [2.0, 2.0, 1.0]
    cells = _cells(project)
    assert cells[added.id] == (0, 1, 1, 1)
    assert cells[right.id] == (0, 2, 1, 1)
    assert cells[wide.id] == (1, 0, 1, 3)
    assert validate_references(project) == []


def test_an_inset_sits_in_its_panel() -> None:
    axes = Axes()
    project = _project(axes)
    history, inset = _apply(project, axes.id, "inset")
    assert inset.inset == Inset(parent=axes.id)
    assert history.undo_text == "Add inset"
    assert validate_references(project) == []
    with pytest.raises(CommandError, match="inset"):
        add_panel(project, inset.id, "right")


def test_removing_a_panel_removes_its_insets() -> None:
    axes, other = Axes(col=0), Axes(col=1)
    project = _project(axes, other, cols=2)
    history, inset = _apply(project, axes.id, "inset")
    history.push(remove_axes(project, axes.id))
    assert [a.id for a in project.figures[0].axes] == [other.id]
    history.undo()
    assert [a.id for a in project.figures[0].axes] == [axes.id, other.id, inset.id]


def test_an_inset_needs_a_panel_in_the_grid() -> None:
    axes = Axes()
    stray = Axes(inset=Inset(parent="gone"), row=5)  # row is not checked for it
    issues = validate_references(_project(axes, stray))
    assert [i.object_id for i in issues] == [stray.id]
    assert "not a panel" in issues[0].message
