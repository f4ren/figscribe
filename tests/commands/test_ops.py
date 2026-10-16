"""Removing objects together with what depends on them, as one undo step."""

from __future__ import annotations

import pytest

from figscribe.commands import CommandError, History, remove_artist, remove_axes
from figscribe.model import (
    Annotation,
    ColumnRef,
    FitCurve,
    LinePlot,
    PredefinedFit,
    Project,
    ResidualPlot,
    dumps,
    validate_references,
)


def _kinds(project: Project) -> list[list[str]]:
    return [[a.kind for a in axes.artists] for axes in project.figures[0].axes]


def test_removing_data_removes_its_fit_and_residuals(project: Project) -> None:
    data = project.figures[0].axes[0].artists[0]
    history = History(project)
    before = dumps(project)

    history.push(remove_artist(project, data.id))

    assert _kinds(project) == [[], []]
    assert validate_references(project) == []
    assert history.undo_text == "Remove errorbar plot"

    history.undo()
    assert dumps(project) == before
    assert not history.can_undo  # it was a single step


def test_the_emptied_residual_panel_stays(project: Project) -> None:
    data = project.figures[0].axes[0].artists[0]
    remove_artist(project, data.id).apply(project)
    assert len(project.figures[0].axes) == 2
    assert project.figures[0].layout.rows == 2


def test_removing_a_fit_removes_only_its_residuals(project: Project) -> None:
    fit = project.figures[0].axes[0].artists[1]
    remove_artist(project, fit.id).apply(project)
    assert _kinds(project) == [["errorbar"], []]
    assert validate_references(project) == []


def test_removing_residuals_removes_nothing_else(project: Project) -> None:
    residuals = project.figures[0].axes[1].artists[0]
    remove_artist(project, residuals.id).apply(project)
    assert _kinds(project) == [["errorbar", "fit"], []]


def test_artists_without_dependents_are_removed_alone(project: Project) -> None:
    top = project.figures[0].axes[0]
    note = Annotation(text="peak", position=(0.0, 1.0))
    top.artists = [*top.artists, note]
    remove_artist(project, note.id).apply(project)
    assert _kinds(project) == [["errorbar", "fit"], ["residual"]]


def test_every_fit_of_the_target_goes(project: Project) -> None:
    top = project.figures[0].axes[0]
    data = top.artists[0]
    second = FitCurve(target=data.id, model=PredefinedFit(name="linear"))
    top.artists = [*top.artists, second]
    bottom = project.figures[0].axes[1]
    bottom.artists = [*bottom.artists, ResidualPlot(target=second.id)]

    history = History(project)
    before = dumps(project)
    history.push(remove_artist(project, data.id))
    assert _kinds(project) == [[], []]
    history.undo()
    assert dumps(project) == before


def test_removing_an_axes_removes_residuals_of_its_fits(project: Project) -> None:
    top = project.figures[0].axes[0]
    history = History(project)
    before = dumps(project)

    history.push(remove_axes(project, top.id))

    assert [len(a.artists) for a in project.figures[0].axes] == [0]
    assert validate_references(project) == []
    history.undo()
    assert dumps(project) == before


def test_removing_an_axes_keeps_unrelated_artists(project: Project) -> None:
    bottom = project.figures[0].axes[1]
    source = project.sources[0].id
    line = LinePlot(
        x=ColumnRef(source=source, column="t"), y=ColumnRef(source=source, column="U")
    )
    bottom.artists = [*bottom.artists, line]
    remove_axes(project, bottom.id).apply(project)
    assert _kinds(project) == [["errorbar", "fit"]]


@pytest.mark.parametrize("make", [remove_artist, remove_axes])
def test_unknown_or_wrong_ids_are_refused(project: Project, make) -> None:
    with pytest.raises(CommandError):
        make(project, "nope")
    with pytest.raises(CommandError):
        make(project, project.figures[0].id)  # neither an artist nor an axes
