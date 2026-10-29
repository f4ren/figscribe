"""The everyday actions of U5 as commands: duplicate a plot or a panel, paste a
style, give panels one range. Each is one undo step."""

from __future__ import annotations

import pytest

from figscribe.commands import (
    CommandError,
    History,
    duplicate_artists,
    duplicate_axes,
    paste_style,
    same_range,
)
from figscribe.commands.core import walk
from figscribe.model import (
    Axes,
    ErrorbarPlot,
    FitCurve,
    Inset,
    LinePlot,
    Project,
    ResidualPlot,
    dumps,
    validate_references,
)


def _ids(project: Project) -> list[str]:
    return [obj.id for obj, _, _ in walk(project)]


# --- duplicate a plot ---------------------------------------------------------


def test_a_duplicated_plot_sits_right_after_the_original(project: Project) -> None:
    axes = project.figures[0].axes[0]
    bars, fit = axes.artists
    before = dumps(project)
    history = History(project)
    command, (made,) = duplicate_artists(project, [bars.id])
    history.push(command)
    assert history.undo_text == "Duplicate errorbar plot"
    assert [a.id for a in axes.artists] == [bars.id, made.id, fit.id]
    copy = axes.artists[1]
    assert copy.id != bars.id
    assert copy.label == "measurement (copy)"
    assert copy.x == bars.x and copy.yerr == bars.yerr  # the same data
    assert len(set(_ids(project))) == len(_ids(project))
    assert not validate_references(project)
    history.undo()
    assert dumps(project) == before


def test_a_copy_of_a_plot_without_a_label_stays_without(project: Project) -> None:
    axes = project.figures[0].axes[0]
    line = LinePlot(x=axes.artists[0].x, y=axes.artists[0].y)
    axes.artists.append(line)
    _, (made,) = duplicate_artists(project, [line.id])
    assert made.label is None


def test_several_plots_are_duplicated_in_one_step(project: Project) -> None:
    axes = project.figures[0].axes[0]
    bars, fit = axes.artists
    before = dumps(project)
    history = History(project)
    command, made = duplicate_artists(project, [bars.id, fit.id])
    history.push(command)
    assert history.undo_text == "Duplicate 2 plots"
    order = [a.id for a in axes.artists]
    assert order == [bars.id, made[0].id, fit.id, made[1].id]
    # The copy of the fit fits the copy of the data, as both were chosen.
    assert isinstance(axes.artists[3], FitCurve)
    assert axes.artists[3].target == made[0].id
    assert not validate_references(project)
    history.undo()
    assert dumps(project) == before


def test_a_fit_copied_alone_still_fits_the_original(project: Project) -> None:
    axes = project.figures[0].axes[0]
    bars, fit = axes.artists
    _, (made,) = duplicate_artists(project, [fit.id])
    assert made.target == bars.id
    assert made.result == fit.result


def test_residuals_are_not_duplicated(project: Project) -> None:
    residuals = project.figures[0].axes[1].artists[0]
    assert isinstance(residuals, ResidualPlot)
    with pytest.raises(CommandError, match="Residuals"):
        duplicate_artists(project, [residuals.id])


def test_a_plot_that_is_not_there_is_refused(project: Project) -> None:
    with pytest.raises(CommandError, match="no artist"):
        duplicate_artists(project, ["nope"])


# --- duplicate a panel --------------------------------------------------------


def test_a_duplicated_panel_goes_to_the_right_with_its_plots(
    project: Project,
) -> None:
    figure = project.figures[0]
    top = figure.axes[0]
    bars, fit = top.artists
    before = dumps(project)
    history = History(project)
    command, made = duplicate_axes(project, top.id)
    history.push(command)
    assert history.undo_text == "Duplicate panel"
    assert figure.layout.cols == 2
    copy = next(a for a in figure.axes if a.id == made.id)
    assert (copy.row, copy.col) == (0, 1)
    assert copy.id != top.id
    assert [type(a) for a in copy.artists] == [ErrorbarPlot, FitCurve]
    assert {a.id for a in copy.artists}.isdisjoint({bars.id, fit.id})
    assert copy.artists[1].target == copy.artists[0].id  # its own data, not ours
    assert copy.artists[0].x == bars.x  # the same data file
    assert copy.legend == top.legend
    assert len(set(_ids(project))) == len(_ids(project))
    assert not validate_references(project)
    history.undo()
    assert dumps(project) == before


def test_a_duplicated_panel_takes_its_insets_along(project: Project) -> None:
    figure = project.figures[0]
    top = figure.axes[0]
    figure.axes.append(
        Axes(
            inset=Inset(parent=top.id, bounds=(0.6, 0.6, 0.3, 0.3)),
            artists=[LinePlot(x=top.artists[0].x, y=top.artists[0].y)],
        )
    )
    command, made = duplicate_axes(project, top.id)
    command.apply(project)
    insets = [a for a in figure.axes if a.inset is not None]
    assert len(insets) == 2
    copy = next(a for a in insets if a.inset.parent == made.id)
    assert copy.inset.bounds == (0.6, 0.6, 0.3, 0.3)
    assert copy.id != insets[0].id
    assert not validate_references(project)


def test_a_copy_beside_a_panel_in_a_free_cell_uses_it(project: Project) -> None:
    figure = project.figures[0]
    duplicate_axes(project, figure.axes[0].id)[0].apply(project)
    assert figure.layout.cols == 2
    # The cell beside the lower panel is free, so its copy goes there.
    command, made = duplicate_axes(project, figure.axes[1].id)
    command.apply(project)
    assert figure.layout.cols == 2
    assert (made.row, made.col) == (1, 1)


def test_an_inset_cannot_be_duplicated(project: Project) -> None:
    figure = project.figures[0]
    inset = Axes(inset=Inset(parent=figure.axes[0].id))
    figure.axes.append(inset)
    with pytest.raises(CommandError, match="inset"):
        duplicate_axes(project, inset.id)


# --- paste a style ------------------------------------------------------------


def test_a_pasted_style_is_the_copied_one_even_after_a_change(
    project: Project,
) -> None:
    axes = project.figures[0].axes[0]
    bars = axes.artists[0]
    line = LinePlot(x=bars.x, y=bars.y)
    axes.artists.append(line)
    bars.color = "tab:red"
    snapshot = bars.model_copy(deep=True)
    bars.color = "tab:green"  # changed after it was copied
    history = History(project)
    command = paste_style(project, [line.id], snapshot)
    history.push(command)
    assert line.color == "tab:red"
    assert history.undo_text == "Paste style"
    history.undo()
    assert line.color != "tab:red"


def test_a_style_goes_to_several_plots_as_one_step(project: Project) -> None:
    axes = project.figures[0].axes[0]
    bars = axes.artists[0]
    first = LinePlot(x=bars.x, y=bars.y)
    second = LinePlot(x=bars.x, y=bars.y)
    axes.artists += [first, second]
    bars.color = "tab:purple"
    bars.linewidth = 3.0
    history = History(project)
    history.push(paste_style(project, [first.id, second.id], bars.model_copy()))
    assert (first.color, second.color) == ("tab:purple", "tab:purple")
    assert (first.linewidth, second.linewidth) == (3.0, 3.0)
    assert history.undo_text == "Paste style to 2 plots"
    history.undo()
    assert first.color != "tab:purple" and second.color != "tab:purple"


def test_a_style_the_plot_already_has_changes_nothing(project: Project) -> None:
    bars = project.figures[0].axes[0].artists[0]
    assert not paste_style(project, [bars.id], bars.model_copy()).steps


# --- the same range in all panels ---------------------------------------------


def test_every_panel_gets_the_range(project: Project) -> None:
    figure = project.figures[0]
    top, bottom = figure.axes
    before = dumps(project)
    history = History(project)
    command, skipped = same_range(project, top.id, "x", (0.0, 8.0))
    history.push(command)
    assert not skipped
    assert history.undo_text == "Same x range in all panels"
    assert top.x.limits == (0.0, 8.0) and bottom.x.limits == (0.0, 8.0)
    assert top.y.limits is None  # the other axis is left alone
    history.undo()
    assert dumps(project) == before


def test_the_order_of_a_turned_axis_is_kept(project: Project) -> None:
    top, bottom = project.figures[0].axes
    same_range(project, top.id, "y", (5.0, -1.0))[0].apply(project)
    assert bottom.y.limits == (5.0, -1.0)


def test_panels_that_already_have_it_are_not_touched(project: Project) -> None:
    top, bottom = project.figures[0].axes
    top.x.limits = bottom.x.limits = (0.0, 8.0)
    assert not same_range(project, top.id, "x", (0.0, 8.0))[0].steps


def test_a_panel_with_another_scale_or_unit_is_skipped(project: Project) -> None:
    figure = project.figures[0]
    top, bottom = figure.axes
    log = Axes(row=2)
    log.x.scale = "log"
    hours = Axes(row=3)
    hours.x.unit = "h"
    figure.axes += [log, hours]
    command, skipped = same_range(project, top.id, "x", (1.0, 8.0))
    command.apply(project)
    assert [a.id for a in skipped] == [log.id, hours.id]
    assert bottom.x.limits == (1.0, 8.0)
    assert log.x.limits is None and hours.x.limits is None


def test_insets_and_other_figures_keep_their_ranges(project: Project) -> None:
    figure = project.figures[0]
    inset = Axes(inset=Inset(parent=figure.axes[0].id))
    figure.axes.append(inset)
    same_range(project, figure.axes[0].id, "x", (0.0, 8.0))[0].apply(project)
    assert inset.x.limits is None


def test_a_range_needs_a_panel_and_an_axis(project: Project) -> None:
    with pytest.raises(CommandError, match="no axes"):
        same_range(project, "nope", "x", (0.0, 1.0))
    with pytest.raises(CommandError, match="x or y"):
        same_range(project, project.figures[0].axes[0].id, "z", (0.0, 1.0))
