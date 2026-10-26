"""Cross-object checks that per-object validation cannot express.

Pydantic validates one object at a time, so it cannot know whether a
`ColumnRef` names a source that exists or whether an `Axes` fits in its grid.
These checks live here, outside the model classes, to keep the model dumb.
`loads()` deliberately does not call them, so that a project file with a dangling
reference can still be opened and repaired; callers run them after loading and
before rendering. They return a list of issues rather than raising, so the GUI
can show all of them at once.

A conflict within one source, such as a decimal separator that is also the
delimiter, is reported here too rather than refused by pydantic, for the same
reason: the file stays loadable.
"""

from __future__ import annotations

from collections.abc import Callable, Sized
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from figscribe.model.artists import (
    ArtistBase,
    ColorMesh,
    ErrorbarPlot,
    FitCurve,
    Histogram,
    ImagePlot,
    LinePlot,
    ReferenceLine,
    ResidualPlot,
    ScatterPlot,
    ShadedSpan,
)
from figscribe.model.axes import Axes
from figscribe.model.data import ArrayRef, ColumnRef, CsvSource, DataSource
from figscribe.model.figure import Figure
from figscribe.model.project import Project
from figscribe.model.styles import style_problems

FITTABLE = (LinePlot, ScatterPlot, ErrorbarPlot)
"""Artist types a FitCurve can target: the ones with x and y columns."""


@dataclass(frozen=True)
class ReferenceIssue:
    """One problem found in a project. Not part of the file format."""

    location: str
    """Dotted path to the offending field, e.g. "figures[0].axes[1].artists[0].x"."""
    object_id: str | None
    """Id of the nearest identified object, so the GUI can select it."""
    message: str

    def __str__(self) -> str:
        return f"{self.location}: {self.message}"


def validate_references(
    project: Project, data: Callable[[ColumnRef], Sized] | None = None
) -> list[ReferenceIssue]:
    """Return every cross-object problem in `project`, empty list if sound.

    With `data`, the columns of each plot are also checked for equal length.
    """
    issues: list[ReferenceIssue] = []
    source_ids = {s.id for s in project.sources}
    sources = {s.id: s for s in project.sources}

    _check_unique_ids(project, issues)

    for si, source in enumerate(project.sources):
        if isinstance(source, CsvSource) and source.decimal == source.delimiter:
            issues.append(
                ReferenceIssue(
                    f"sources[{si}].decimal",
                    source.id,
                    f"decimal separator {source.decimal!r} is also the delimiter",
                )
            )

    for fi, figure in enumerate(project.figures):
        fpath = f"figures[{fi}]"
        _check_grid(figure, fpath, issues)
        for field, why in style_problems(figure):
            issues.append(ReferenceIssue(f"{fpath}.{field}", figure.id, why))

        fit_ids = {
            a.id
            for axes in figure.axes
            for a in axes.artists
            if isinstance(a, FitCurve)
        }

        for ai, axes in enumerate(figure.axes):
            apath = f"{fpath}.axes[{ai}]"
            _check_axis_ticks(axes, apath, issues)
            _check_minor_grid(axes, apath, issues)

            artists_by_id = {a.id: a for a in axes.artists}
            for field, why in style_problems(axes):
                issues.append(ReferenceIssue(f"{apath}.{field}", axes.id, why))

            for ti, artist in enumerate(axes.artists):
                tpath = f"{apath}.artists[{ti}]"
                for field, why in style_problems(artist):
                    issues.append(ReferenceIssue(f"{tpath}.{field}", artist.id, why))

                if artist.axis == "right" and axes.y_right is None:
                    issues.append(
                        ReferenceIssue(
                            tpath,
                            artist.id,
                            "draws against the right y-axis, "
                            "but the axes has no y_right",
                        )
                    )

                why = _off_the_log_scale(artist, axes)
                if why is not None:
                    issues.append(ReferenceIssue(tpath, artist.id, why))
                if getattr(artist, "band", None) and artist.yerr is None:
                    issues.append(
                        ReferenceIssue(
                            f"{tpath}.band",
                            artist.id,
                            "has an error band but no y errors to shade",
                        )
                    )

                if data is not None and isinstance(artist, FITTABLE):
                    why = _unequal_or_unreadable(artist, data)
                    if why is not None:
                        issues.append(ReferenceIssue(tpath, artist.id, why))
                if data is not None:
                    for why in _not_drawn(artist, axes, data):
                        issues.append(ReferenceIssue(tpath, artist.id, why))

                for field, ref in data_refs(artist):
                    if ref not in source_ids:
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.{field}",
                                artist.id,
                                f"references unknown data source {ref!r}",
                            )
                        )
                for field, column in _columns(artist):
                    source = sources.get(column.source)
                    if source is not None and _lacks(source, column):
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.{field}",
                                artist.id,
                                f"uses the column {column.column!r}, which "
                                f"{Path(source.path).name} does not have",
                            )
                        )

                if isinstance(artist, FitCurve):
                    target = artists_by_id.get(artist.target)
                    if target is None:
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.target",
                                artist.id,
                                f"fits artist {artist.target!r}, "
                                "which is not in this axes",
                            )
                        )
                    elif not isinstance(target, FITTABLE):
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.target",
                                artist.id,
                                f"fits artist {artist.target!r}, which is not a data "
                                f"artist but a {target.kind!r}",
                            )
                        )
                    _check_fit_parameters(artist, tpath, issues)

                if isinstance(artist, ResidualPlot) and artist.target not in fit_ids:
                    issues.append(
                        ReferenceIssue(
                            f"{tpath}.target",
                            artist.id,
                            f"references {artist.target!r}, "
                            "which is not a fit in this figure",
                        )
                    )

                if isinstance(artist, Histogram) and isinstance(artist.bins, list):
                    edges = artist.bins
                    if len(edges) < 2:
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.bins",
                                artist.id,
                                "explicit bin edges need at least two values",
                            )
                        )
                    elif any(b <= a for a, b in pairwise(edges)):
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.bins",
                                artist.id,
                                "bin edges must increase strictly",
                            )
                        )

    return issues


def missing_columns(project: Project) -> list[tuple[ArtistBase, str, ColumnRef]]:
    """(plot, field, reference) for every column a plot uses by name that its
    data file does not have, e.g. after the file changed."""
    sources = {s.id: s for s in project.sources}
    return [
        (artist, field, column)
        for figure in project.figures
        for axes in figure.axes
        for artist in axes.artists
        for field, column in _columns(artist)
        if column.source in sources and _lacks(sources[column.source], column)
    ]


def _columns(artist: ArtistBase) -> list[tuple[str, ColumnRef]]:
    return [
        (name, value)
        for name in type(artist).model_fields
        if isinstance(value := getattr(artist, name), ColumnRef)
    ]


def _lacks(source: DataSource, column: ColumnRef) -> bool:
    """Whether `column` names a column the source's file does not have; files
    without column names are addressed by number and not checked here."""
    return (
        isinstance(column.column, str)
        and bool(source.columns)
        and column.column not in source.columns
    )


def unequal_columns(
    artist: LinePlot | ScatterPlot | ErrorbarPlot,
    data: Callable[[ColumnRef], Sized],
) -> str | None:
    """Why the columns of a plot cannot be drawn together: the first that has
    another number of values than x. None if they all match."""
    (first, base), *others = [
        (name, ref)
        for name in ("x", "y", "xerr", "yerr")
        if (ref := getattr(artist, name, None)) is not None
    ]
    count = len(data(base))
    for name, ref in others:
        if (other := len(data(ref))) != count:
            return (
                f"{name} ({ref.column}) has {other} values, "
                f"{first} ({base.column}) has {count}"
            )
    return None


def _unequal_or_unreadable(artist, data) -> str | None:
    # Imported here: the data package imports the model.
    from figscribe.io.errors import DataError

    try:
        return unequal_columns(artist, data)
    except DataError:
        return None  # a file that cannot be read is shown above the preview


def _off_the_log_scale(artist, axes: Axes) -> str | None:
    """Why a reference line or shaded range cannot be seen on its log axis."""
    if not isinstance(artist, ReferenceLine | ShadedSpan):
        return None
    if artist.orientation == "vertical":
        spec = axes.x
    else:
        right = artist.axis == "right" and axes.y_right is not None
        spec = axes.y_right if right else axes.y
    if spec.scale != "log":
        return None
    if isinstance(artist, ReferenceLine):
        where = f"is at {artist.at:g}" if artist.at <= 0 else None
    else:
        low = min(artist.start, artist.end)
        where = f"starts at {low:g}" if low <= 0 else None
    return f"{where}, which a log scale does not show" if where else None


def _not_drawn(artist, axes: Axes, data) -> list[str]:
    """What of the artist's data cannot be seen: a column without a finite
    value, or values at or below zero on a log axis or color scale."""
    # Imported here: the data package imports the model, and NumPy is only
    # needed once there is data.
    import numpy as np

    from figscribe.io.errors import DataError

    right = getattr(artist, "axis", "left") == "right" and axes.y_right is not None
    y_scale = (axes.y_right if right else axes.y).scale
    shown: list[tuple[str, object, str]] = []  # (name, reference, scale)
    if isinstance(artist, FITTABLE):
        shown = [("x", artist.x, axes.x.scale), ("y", artist.y, y_scale)]
    elif isinstance(artist, Histogram):
        shown = [("values", artist.values, axes.x.scale)]
    elif isinstance(artist, ImagePlot | ColorMesh):
        reference = artist.data if isinstance(artist, ImagePlot) else artist.c
        shown = [("values", reference, artist.norm)]
    found = []
    if isinstance(artist, FITTABLE) and artist.left_out:
        try:
            count = len(data(artist.x))
        except DataError:
            return []
        for row in artist.left_out:
            if row >= count:
                found.append(
                    f"row {row + 1} is left out, but the data has {count} rows"
                )
                break
    for name, reference, scale in shown:
        try:
            values = np.asarray(data(reference), dtype=float).ravel()
        except DataError:
            return []  # a file that cannot be read is shown above the preview
        what = (
            f"{name} ({reference.column})" if isinstance(reference, ColumnRef) else name
        )
        finite = values[np.isfinite(values)]
        if values.size and not finite.size:
            found.append(f"{what} has no values to draw")
        elif scale == "log" and (below := int(np.count_nonzero(finite <= 0))):
            found.append(
                f"{below} of {values.size} values of {what} are zero or below, "
                "which a log scale does not show"
            )
    return found


def data_refs(artist: ArtistBase) -> list[tuple[str, str]]:
    """Return (field name, source id) for every data reference on `artist`.

    Walks the declared fields instead of listing them per artist type, so that a
    newly added artist cannot slip past this check.
    """
    refs: list[tuple[str, str]] = []
    for name in type(artist).model_fields:
        value = getattr(artist, name)
        if isinstance(value, (ColumnRef, ArrayRef)):
            refs.append((name, value.source))
    return refs


def _check_unique_ids(project: Project, issues: list[ReferenceIssue]) -> None:
    seen: dict[str, str] = {}
    for si, source in enumerate(project.sources):
        _see(seen, source.id, f"sources[{si}]", issues)
    for fi, figure in enumerate(project.figures):
        _see(seen, figure.id, f"figures[{fi}]", issues)
        for ai, axes in enumerate(figure.axes):
            _see(seen, axes.id, f"figures[{fi}].axes[{ai}]", issues)
            for ti, artist in enumerate(axes.artists):
                _see(
                    seen,
                    artist.id,
                    f"figures[{fi}].axes[{ai}].artists[{ti}]",
                    issues,
                )


def _see(
    seen: dict[str, str],
    oid: str,
    location: str,
    issues: list[ReferenceIssue],
) -> None:
    if oid in seen:
        issues.append(
            ReferenceIssue(location, oid, f"duplicate id, already used by {seen[oid]}")
        )
    else:
        seen[oid] = location


def _check_fit_parameters(
    fit: FitCurve, path: str, issues: list[ReferenceIssue]
) -> None:
    """Fixed and bounded parameters must be the model's."""
    if not fit.fixed and not fit.parameter_bounds:
        return
    # Imported here: the fit package needs SciPy, which reading a model must not.
    from figscribe.fit import FitError, parameter_names

    try:
        names = parameter_names(fit.model)
    except (FitError, ValueError):
        return  # an expression that does not compile is reported when fitted
    for name in fit.fixed:
        if name not in names:
            issues.append(
                ReferenceIssue(
                    f"{path}.fixed",
                    fit.id,
                    f"holds {name!r} fixed, which the model does not have",
                )
            )
    for name in fit.parameter_bounds:
        if name not in names:
            issues.append(
                ReferenceIssue(
                    f"{path}.parameter_bounds",
                    fit.id,
                    f"bounds {name!r}, which the model does not have",
                )
            )


def _check_grid(figure: Figure, path: str, issues: list[ReferenceIssue]) -> None:
    layout = figure.layout

    for name, ratios, expected in (
        ("width_ratios", layout.width_ratios, layout.cols),
        ("height_ratios", layout.height_ratios, layout.rows),
    ):
        if ratios is not None and len(ratios) != expected:
            issues.append(
                ReferenceIssue(
                    f"{path}.layout.{name}",
                    figure.id,
                    f"has {len(ratios)} values, but the grid has {expected}",
                )
            )

    in_grid = {a.id for a in figure.axes if a.inset is None}
    for ai, axes in enumerate(figure.axes):
        if axes.inset is not None and axes.inset.parent not in in_grid:
            issues.append(
                ReferenceIssue(
                    f"{path}.axes[{ai}].inset.parent",
                    axes.id,
                    f"sits in {axes.inset.parent!r}, which is not a panel "
                    "in this figure's grid",
                )
            )
    _check_spans(figure, path, issues)


def outside_the_grid(project: Project) -> list[ReferenceIssue]:
    """Panels that reach beyond their figure's grid, which cannot be drawn."""
    issues: list[ReferenceIssue] = []
    for fi, figure in enumerate(project.figures):
        _check_spans(figure, f"figures[{fi}]", issues)
    return issues


def _check_spans(figure: Figure, path: str, issues: list[ReferenceIssue]) -> None:
    layout = figure.layout
    for ai, axes in enumerate(figure.axes):
        if axes.inset is not None:
            continue  # an inset is placed by its bounds
        if axes.row + axes.rowspan > layout.rows:
            issues.append(
                ReferenceIssue(
                    f"{path}.axes[{ai}]",
                    axes.id,
                    f"spans rows {axes.row}-{axes.row + axes.rowspan - 1}, "
                    f"but the grid has {layout.rows}",
                )
            )
        if axes.col + axes.colspan > layout.cols:
            issues.append(
                ReferenceIssue(
                    f"{path}.axes[{ai}]",
                    axes.id,
                    f"spans columns {axes.col}-{axes.col + axes.colspan - 1}, "
                    f"but the grid has {layout.cols}",
                )
            )


def _check_minor_grid(axes: Axes, path: str, issues: list[ReferenceIssue]) -> None:
    """Grid lines only at minor ticks, on axes that have none, draw nothing."""
    if not axes.grid or axes.grid_which != "minor":
        return
    names = ("x", "y") if axes.grid_axis == "both" else (axes.grid_axis,)
    if not any(getattr(axes, name).minor_ticks for name in names):
        which = "the axes have" if len(names) == 2 else f"the {names[0]} axis has"
        issues.append(
            ReferenceIssue(
                f"{path}.grid_which",
                axes.id,
                f"draws grid lines at minor ticks, but {which} none; switch "
                "them on in the axis or draw the lines at the numbered ticks",
            )
        )


def _check_axis_ticks(axes: Axes, path: str, issues: list[ReferenceIssue]) -> None:
    # Imported here: the renderer imports the model, and listing the assistant
    # tools must not load Matplotlib.
    from figscribe.render.ticks import too_many_ticks

    for name in ("x", "y", "y_right"):
        spec = getattr(axes, name)
        if spec is None:
            continue
        # An automatic range depends on the data, which is not known here; the
        # renderer falls back to automatic ticks in either case.
        if spec.limits is not None:
            problem = too_many_ticks(spec, spec.limits)
            if problem is not None:
                field, message = problem
                issues.append(
                    ReferenceIssue(f"{path}.{name}.{field}", axes.id, message)
                )
        if spec.tick_labels is None:
            continue
        if spec.ticks is None:
            issues.append(
                ReferenceIssue(
                    f"{path}.{name}.tick_labels",
                    axes.id,
                    "tick labels given without tick positions",
                )
            )
        elif len(spec.tick_labels) != len(spec.ticks):
            issues.append(
                ReferenceIssue(
                    f"{path}.{name}.tick_labels",
                    axes.id,
                    f"has {len(spec.tick_labels)} labels for {len(spec.ticks)} ticks",
                )
            )
