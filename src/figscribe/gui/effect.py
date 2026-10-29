"""Settings that do nothing in the state they are in, and why.

The property panel greys such a field out and says in its tooltip what it
waits for, instead of letting a change go unseen. Each rule is checked
against the renderer in tests/gui/test_without_effect.py: while it holds, a
change of the field leaves the figure as it was.

A combination that draws nothing although each field does something (grid
lines at minor ticks on axes without minor ticks) is not a rule here but a
problem in the list, from `validate_references`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from figscribe.model import (
    AllanDeviationPlot,
    Axes,
    ColorMesh,
    ErrorbarPlot,
    FitCurve,
    ImagePlot,
    LinePlot,
    Project,
    ReferenceLine,
    ScatterPlot,
)
from figscribe.render.figure import NO_LINE

Path = tuple[str, ...]


@dataclass(frozen=True)
class Rule:
    owners: tuple[type[BaseModel], ...]
    """The classes whose fields the rule is about."""
    paths: tuple[Path, ...]
    """The fields, as paths within the object."""
    why: str
    """What the fields wait for, after "Does nothing while"."""
    holds: Callable[[BaseModel, Project], bool]
    """Whether the fields do nothing now."""


def _left_out_nowhere(plot, project: Project) -> bool:
    """No rows of `plot` are drawn as left out: none are, and no fit of it
    draws the points outside its range that way."""
    if plot.left_out:
        return False
    for figure in project.figures:
        for axes in figure.axes:
            for fit in axes.artists:
                if (
                    isinstance(fit, FitCurve)
                    and fit.target == plot.id
                    and fit.outside_as_left_out
                    and fit.fit_range is not None
                ):
                    return False
    return True


def _no_bars(plot: ErrorbarPlot, _) -> bool:
    """No error bars are drawn: no errors, or only y errors drawn as a band."""
    return plot.xerr is None and (plot.yerr is None or plot.band is not None)


GRID = ("grid_axis", "grid_which", "grid_color", "grid_linewidth", "grid_linestyle")
LEGEND = ("position", "frame", "ncols", "fontsize")
LEFT_OUT = ("left_out_color", "left_out_marker", "left_out_linestyle")

RULES: list[Rule] = [
    Rule(
        (Axes,),
        tuple((name,) for name in GRID),
        "the grid lines are off",
        lambda axes, _: not axes.grid,
    ),
    Rule(
        (Axes,),
        tuple(("legend", name) for name in LEGEND),
        "the legend is hidden",
        lambda axes, _: not axes.legend.visible,
    ),
    Rule(
        (Axes,),
        (("legend", "location"),),
        "the legend is hidden, or placed by dragging (clear its position to "
        "use a location)",
        lambda axes, _: not axes.legend.visible or axes.legend.position is not None,
    ),
    Rule(
        (LinePlot, ErrorbarPlot, AllanDeviationPlot),
        (("linewidth",),),
        'there is no line: its line style is "none"',
        lambda plot, _: plot.linestyle in NO_LINE,
    ),
    Rule(
        (LinePlot, AllanDeviationPlot),
        (("markersize",),),
        "the plot has no marker",
        lambda plot, _: plot.marker is None,
    ),
    Rule(
        (ErrorbarPlot,),
        (("capsize",), ("elinewidth",)),
        "no error bars are drawn: the y errors are a band, and there are no x errors",
        _no_bars,
    ),
    Rule(
        (LinePlot, ScatterPlot, ErrorbarPlot),
        tuple((name,) for name in LEFT_OUT),
        "no points are left out (right-click a point in the figure to leave it out)",
        _left_out_nowhere,
    ),
    # Not for a shaded range: on the right axis it lies in another layer.
    Rule(
        (ReferenceLine,),
        (("axis",),),
        "the line is vertical: it lies along x, whichever y axis it belongs to",
        lambda line, _: line.orientation == "vertical",
    ),
    Rule(
        (AllanDeviationPlot,),
        (("sample_interval",),),
        "a column of times gives the interval",
        lambda plot, _: plot.time is not None,
    ),
    Rule(
        (ImagePlot, ColorMesh),
        (("colorbar", "label"),),
        "the color bar is hidden",
        lambda plot, _: plot.colorbar is not None and not plot.colorbar.visible,
    ),
    Rule(
        (FitCurve,),
        (("extend_curve",), ("outside_as_left_out",)),
        "the fit uses all the data: set a range in the fit dialog",
        lambda fit, _: fit.fit_range is None,
    ),
]


def without_effect(obj: BaseModel, path: Path, project: Project) -> str | None:
    """Why the field at `path` of `obj` does nothing now; None if it counts."""
    for rule in RULES:
        if isinstance(obj, rule.owners) and path in rule.paths:
            if rule.holds(obj, project):
                return f"Does nothing while {rule.why}."
    return None
