"""Cross-object checks that per-object validation cannot express.

Pydantic validates one object at a time, so it cannot know whether a
`ColumnRef` names a source that exists or whether an `Axes` fits in its grid.
These checks live here, outside the model classes, to keep the model dumb.
`loads()` deliberately does not call them, so that a project file with a dangling
reference can still be opened and repaired; callers run them after loading and
before rendering. They return a list of issues rather than raising, so the GUI
can show all of them at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from figscribe.model.artists import (
    Annotation,
    ColorMesh,
    ErrorbarPlot,
    FitCurve,
    Histogram,
    ImagePlot,
    LinePlot,
    ResidualPlot,
    ScatterPlot,
)
from figscribe.model.project import Project


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


def validate_references(project: Project) -> list[ReferenceIssue]:
    """Return every cross-object problem in `project`, empty list if sound."""
    issues: list[ReferenceIssue] = []
    source_ids = {s.id for s in project.sources}

    _check_unique_ids(project, issues)

    for fi, figure in enumerate(project.figures):
        fpath = f"figures[{fi}]"
        _check_grid(figure, fpath, issues)

        fit_ids = {
            a.id
            for axes in figure.axes
            for a in axes.artists
            if isinstance(a, FitCurve)
        }

        for ai, axes in enumerate(figure.axes):
            apath = f"{fpath}.axes[{ai}]"
            _check_axis_ticks(axes, apath, issues)

            artist_ids = {a.id for a in axes.artists}

            for ti, artist in enumerate(axes.artists):
                tpath = f"{apath}.artists[{ti}]"

                if artist.axis == "right" and axes.y_right is None:
                    issues.append(
                        ReferenceIssue(
                            tpath,
                            artist.id,
                            'draws against the right y-axis, but the axes has no y_right',
                        )
                    )

                for field, ref in _data_refs(artist):
                    if ref not in source_ids:
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.{field}",
                                artist.id,
                                f"references unknown data source {ref!r}",
                            )
                        )

                if isinstance(artist, FitCurve) and artist.target not in artist_ids:
                    issues.append(
                        ReferenceIssue(
                            f"{tpath}.target",
                            artist.id,
                            f"fits artist {artist.target!r}, which is not in this axes",
                        )
                    )

                if isinstance(artist, ResidualPlot) and artist.target not in fit_ids:
                    issues.append(
                        ReferenceIssue(
                            f"{tpath}.target",
                            artist.id,
                            f"references {artist.target!r}, which is not a fit in this figure",
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
                    elif any(b <= a for a, b in zip(edges, edges[1:])):
                        issues.append(
                            ReferenceIssue(
                                f"{tpath}.bins",
                                artist.id,
                                "bin edges must increase strictly",
                            )
                        )

    return issues


def _data_refs(artist: object) -> list[tuple[str, str]]:
    """Return (field name, source id) for every data reference on `artist`."""
    refs: list[tuple[str, str]] = []
    if isinstance(artist, (LinePlot, ScatterPlot, ErrorbarPlot)):
        refs += [("x", artist.x.source), ("y", artist.y.source)]
        if isinstance(artist, ErrorbarPlot):
            for name in ("xerr", "yerr"):
                ref = getattr(artist, name)
                if ref is not None:
                    refs.append((name, ref.source))
    elif isinstance(artist, Histogram):
        refs.append(("values", artist.values.source))
    elif isinstance(artist, ImagePlot):
        refs.append(("data", artist.data.source))
    elif isinstance(artist, ColorMesh):
        refs.append(("c", artist.c.source))
        for name in ("x", "y"):
            ref = getattr(artist, name)
            if ref is not None:
                refs.append((name, ref.source))
    elif isinstance(artist, (FitCurve, ResidualPlot, Annotation)):
        pass  # these refer to other artists, not to data
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
            ReferenceIssue(
                location, oid, f"duplicate id, already used by {seen[oid]}"
            )
        )
    else:
        seen[oid] = location


def _check_grid(figure: object, path: str, issues: list[ReferenceIssue]) -> None:
    layout = figure.layout  # type: ignore[attr-defined]

    for name, ratios, expected in (
        ("width_ratios", layout.width_ratios, layout.cols),
        ("height_ratios", layout.height_ratios, layout.rows),
    ):
        if ratios is not None and len(ratios) != expected:
            issues.append(
                ReferenceIssue(
                    f"{path}.layout.{name}",
                    figure.id,  # type: ignore[attr-defined]
                    f"has {len(ratios)} values, but the grid has {expected}",
                )
            )

    for ai, axes in enumerate(figure.axes):  # type: ignore[attr-defined]
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


def _check_axis_ticks(axes: object, path: str, issues: list[ReferenceIssue]) -> None:
    for name in ("x", "y", "y_right"):
        spec = getattr(axes, name)
        if spec is None:
            continue
        if spec.tick_labels is None:
            continue
        if spec.ticks is None:
            issues.append(
                ReferenceIssue(
                    f"{path}.{name}.tick_labels",
                    axes.id,  # type: ignore[attr-defined]
                    "tick labels given without tick positions",
                )
            )
        elif len(spec.tick_labels) != len(spec.ticks):
            issues.append(
                ReferenceIssue(
                    f"{path}.{name}.tick_labels",
                    axes.id,  # type: ignore[attr-defined]
                    f"has {len(spec.tick_labels)} labels for "
                    f"{len(spec.ticks)} ticks",
                )
            )
