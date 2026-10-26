"""Adding, duplicating and removing figures, each as one undo step."""

from __future__ import annotations

import pytest

from figscribe.commands import (
    CommandError,
    History,
    add_figure,
    duplicate_figure,
    remove_figure,
)
from figscribe.commands.core import walk
from figscribe.model import (
    Axes,
    FitCurve,
    Inset,
    Project,
    ResidualPlot,
    dumps,
    validate_references,
)


def test_a_new_figure_has_one_empty_panel_and_the_look_of_its_neighbour(
    project: Project,
) -> None:
    scan = project.figures[0]
    scan.font_size = 8.0
    scan.tick_direction = "in"
    history = History(project)
    command, figure = add_figure(project, after=scan.id)
    history.push(command)
    assert project.figures[1] is not figure  # the command holds its own copy
    added = project.figures[1]
    assert added.id == figure.id
    assert added.name == "Figure 2"
    assert (added.width_mm, added.font_size, added.tick_direction) == (85.0, 8.0, "in")
    assert len(added.axes) == 1 and not added.axes[0].artists
    assert (added.layout.rows, added.layout.cols) == (1, 1)
    assert history.undo_text == "Add a figure"
    history.undo()
    assert [f.id for f in project.figures] == [scan.id]


def test_a_new_figure_goes_after_the_given_one_with_a_free_name(
    project: Project,
) -> None:
    History(project).push(add_figure(project)[0])  # Figure 2, at the end
    project.figures[1].name = "Figure 3"
    command, figure = add_figure(project, after=project.figures[0].id)
    command.apply(project)
    assert [f.name for f in project.figures] == ["Scan", "Figure 2", "Figure 3"]
    assert project.figures[1].id == figure.id


def test_a_duplicate_is_a_copy_with_ids_of_its_own(project: Project) -> None:
    scan = project.figures[0]
    scan.axes.append(
        Axes(inset=Inset(parent=scan.axes[0].id, bounds=(0.6, 0.6, 0.3, 0.3)))
    )
    before = dumps(project)
    history = History(project)
    command, copy = duplicate_figure(project, scan.id)
    history.push(command)
    assert history.undo_text == "Duplicate Scan"
    assert [f.name for f in project.figures] == ["Scan", "Scan (copy)"]
    copy = project.figures[1]
    ids = [obj.id for obj, _, _ in walk(project)]
    assert len(ids) == len(set(ids))
    data, fit = copy.axes[0].artists
    (residuals,) = copy.axes[1].artists
    assert isinstance(fit, FitCurve) and fit.target == data.id
    assert isinstance(residuals, ResidualPlot) and residuals.target == fit.id
    assert fit.result == scan.axes[0].artists[1].result
    assert copy.axes[2].inset.parent == copy.axes[0].id
    assert data.x.source == scan.axes[0].artists[0].x.source  # the same data
    assert not validate_references(project)
    history.undo()
    assert dumps(project) == before


def test_a_second_duplicate_is_numbered(project: Project) -> None:
    scan = project.figures[0]
    duplicate_figure(project, scan.id)[0].apply(project)
    duplicate_figure(project, scan.id)[0].apply(project)
    names = [f.name for f in project.figures]
    assert names == ["Scan", "Scan (copy 2)", "Scan (copy)"]


def test_removing_a_figure_and_undoing_it(project: Project) -> None:
    add_figure(project)[0].apply(project)
    before = dumps(project)
    history = History(project)
    scan = project.figures[0]
    history.push(remove_figure(project, scan.id))
    assert history.undo_text == "Remove Scan"
    assert [f.name for f in project.figures] == ["Figure 2"]
    history.undo()
    assert dumps(project) == before


def test_the_last_figure_stays(project: Project) -> None:
    with pytest.raises(CommandError, match="at least one figure"):
        remove_figure(project, project.figures[0].id)


def test_unknown_figures_are_refused(project: Project) -> None:
    with pytest.raises(CommandError, match="no figure"):
        duplicate_figure(project, project.figures[0].axes[0].id)
    with pytest.raises(CommandError, match="no figure"):
        add_figure(project, after="nope")


def test_a_new_figure_keeps_the_panel_letters(project: Project) -> None:
    from figscribe.model import PanelLabels

    project.figures[0].panel_labels = PanelLabels(style="A", bold=True)
    add_figure(project)[0].apply(project)
    assert project.figures[1].panel_labels == PanelLabels(style="A", bold=True)
    assert project.figures[1].panel_labels is not project.figures[0].panel_labels
