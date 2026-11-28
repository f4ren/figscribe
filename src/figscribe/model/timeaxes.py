"""Date axes (decision 0082): which axes show dates, and what is not drawn on
them. The renderer, the code generator and the list of problems all ask here.

An axis is a date axis when a line, scatter or error bar plot draws a column of
times on it as it is, without a conversion to the time since its start. Which
columns are times, the callers say: `is_time(ColumnRef)`.
"""

from __future__ import annotations

from collections.abc import Callable

from figscribe.model.artists import (
    AllanDeviationPlot,
    ColorMesh,
    ErrorbarPlot,
    FitCurve,
    FunctionPlot,
    Histogram,
    ImagePlot,
    LinePlot,
    ResidualPlot,
    ScatterPlot,
)
from figscribe.model.data import ArrayRef, ColumnRef, DataSource
from figscribe.model.figure import Figure
from figscribe.model.project import Project
from figscribe.model.sharing import sharing_group

IsTime = Callable[[ColumnRef], bool]

_POINTS = (LinePlot, ScatterPlot, ErrorbarPlot)

SINCE_START = "show it as the time since the start instead"


def time_columns_of(project: Project) -> IsTime:
    """`is_time` as the project records it."""
    sources: dict[str, DataSource] = {s.id: s for s in project.sources}

    def is_time(ref: ColumnRef) -> bool:
        source = sources.get(ref.source)
        if source is None:
            return False
        column = ref.column
        if isinstance(column, str):
            if column not in source.columns:
                return False
            column = source.columns.index(column)
        return column in source.time_columns

    return is_time


def as_dates(artist, name: str, is_time: IsTime) -> bool:
    """Whether the plot's x or y (`name`) is a column of times drawn as dates."""
    if not isinstance(artist, _POINTS):
        return False
    conversion = getattr(artist, f"{name}_conversion")
    return conversion is None and is_time(getattr(artist, name))


def date_axis(figure: Figure, index: int, field: str, is_time: IsTime) -> bool:
    """Whether the `field` axis ("x", "y" or "y_right") of the panel `index`
    shows dates, by its own plots or those of a panel sharing it."""
    name = "x" if field == "x" else "y"
    for i in sharing_group(figure, index, field):
        axes = figure.axes[i]
        for artist in axes.artists:
            right = artist.axis == "right" and axes.y_right is not None
            if name == "y" and right != (field == "y_right"):
                continue
            if as_dates(artist, name, is_time):
                return True
    return False


def not_on_dates(figure: Figure, index: int, artist, is_time: IsTime) -> str | None:
    """Why the artist of the panel `index` is not drawn, where dates are the
    reason; None if it is drawn. Reference lines, ranges and notes always are."""
    axes = figure.axes[index]
    right = artist.axis == "right" and axes.y_right is not None
    dates = {
        "x": date_axis(figure, index, "x", is_time),
        "y": date_axis(figure, index, "y_right" if right else "y", is_time),
    }
    on_dates = dates["x"] or dates["y"]
    if isinstance(artist, _POINTS):
        return _points(artist, dates, is_time)
    if isinstance(artist, Histogram):
        if artist.x_conversion is None and is_time(artist.values):
            return f"a histogram cannot count dates; {SINCE_START}"
        return "it holds numbers on a date axis" if on_dates else None
    if isinstance(artist, AllanDeviationPlot):
        if is_time(artist.values):
            return "its values are dates"
        return "it cannot be drawn on a date axis" if on_dates else None
    if isinstance(artist, ImagePlot | ColorMesh):
        refs = [getattr(artist, n, None) for n in ("x", "y")]
        if any(isinstance(r, ColumnRef) and is_time(r) for r in refs):
            return "images and color meshes cannot have date axes yet"
        whole = getattr(artist, "data", None) or getattr(artist, "c", None)
        if on_dates and isinstance(whole, ArrayRef):
            return "it cannot be drawn on a date axis"
        return None
    if isinstance(artist, FunctionPlot):
        return "a function cannot be drawn on a date axis" if on_dates else None
    if isinstance(artist, FitCurve | ResidualPlot):
        target = _fitted(figure, artist)
        if target is not None and not isinstance(target, AllanDeviationPlot):
            if any(as_dates(target, n, is_time) for n in ("x", "y")):
                return f"there is no fit to dates; {SINCE_START}"
        about = _about(figure, artist.target)
        if about is not None and not_on_dates(figure, *about, is_time):
            what = "its fit" if isinstance(artist, ResidualPlot) else "the plot it fits"
            return f"{what} is not drawn"
        return "it cannot be drawn on a date axis" if on_dates else None
    return None


def _about(figure: Figure, oid: str):
    """(panel index, artist) of what a fit or residuals are about, if it is in
    the figure."""
    for i, axes in enumerate(figure.axes):
        for artist in axes.artists:
            if artist.id == oid and isinstance(artist, (*_POINTS, FitCurve)):
                return i, artist
    return None


def _points(artist, dates: dict[str, bool], is_time: IsTime) -> str | None:
    for name in ("x", "y"):
        if dates[name] and not as_dates(artist, name, is_time):
            return f"its {name} are numbers, and other plots show dates there"
    for name in ("x", "y"):
        error = getattr(artist, f"{name}err", None)
        if error is None:
            continue
        if is_time(error):
            return f"the {name} errors are dates, not durations"
        if dates[name]:
            return f"dates cannot have {name} errors; {SINCE_START}"
    if artist.baseline is not None:
        if dates["y"]:
            return "dates have no baseline"
        if dates["x"]:
            return f"there is no baseline over dates; {SINCE_START}"
    if artist.smoothing is not None and dates["y"]:
        return "dates cannot be smoothed"
    if artist.normalize is not None and dates["y"]:
        return "dates cannot be normalised"
    if artist.normalize == "area" and dates["x"]:
        return f"there is no area over dates; {SINCE_START}"
    if artist.reduction is not None and (dates["x"] or dates["y"]):
        return f"dates cannot be shown with fewer points; {SINCE_START}"
    return None


def _fitted(figure: Figure, artist):
    """The plot a fit or its residuals are about, if it is in the figure."""
    artists = {a.id: a for axes in figure.axes for a in axes.artists}
    target = artists.get(artist.target)
    if isinstance(target, FitCurve):
        target = artists.get(target.target)
    return target
