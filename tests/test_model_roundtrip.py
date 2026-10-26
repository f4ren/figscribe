"""Test 1 from the project brief: model -> JSON -> model yields equality."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from figscribe.model import (
    SCHEMA_VERSION,
    Axes,
    CsvSource,
    ErrorbarPlot,
    Figure,
    FitCurve,
    Histogram,
    LinePlot,
    Project,
    ResidualPlot,
    SchemaVersionError,
    dumps,
    loads,
)


def test_roundtrip_is_lossless(project: Project) -> None:
    assert loads(dumps(project)) == project


def test_roundtrip_is_idempotent(project: Project) -> None:
    once = dumps(project)
    assert dumps(loads(once)) == once


def test_roundtrip_keeps_the_encoding_of_a_source(project: Project) -> None:
    project.sources[0].encoding = "cp1252"
    assert loads(dumps(project)).sources[0].encoding == "cp1252"


def test_roundtrip_restores_concrete_artist_types(project: Project) -> None:
    axes = loads(dumps(project)).figures[0].axes
    assert [type(a) for a in axes[0].artists] == [ErrorbarPlot, FitCurve]
    assert [type(a) for a in axes[1].artists] == [ResidualPlot]


def test_roundtrip_keeps_nested_unions(project: Project) -> None:
    fit = loads(dumps(project)).figures[0].axes[0].artists[1]
    assert isinstance(fit, FitCurve)
    assert fit.model.name == "gaussian"


def test_roundtrip_keeps_tuples_as_tuples(project: Project) -> None:
    legend = loads(dumps(project)).figures[0].axes[0].legend
    assert legend.position == (0.6, 0.9)
    assert isinstance(legend.position, tuple)


def test_empty_project_roundtrips() -> None:
    assert loads(dumps(Project())) == Project()


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"alpha": 1.5}, "less_than_equal"),
        ({"alpha": -0.1}, "greater_than_equal"),
        ({"linewidth": 0.0}, "greater_than"),
        ({"colour": "red"}, "extra_forbidden"),
    ],
)
def test_artist_validation_rejects(
    kwargs: dict, error_type: str, project: Project
) -> None:
    line = project.figures[0].axes[0].artists[0]
    assert isinstance(line, ErrorbarPlot)
    with pytest.raises(ValidationError) as exc:
        LinePlot(x=line.x, y=line.y, **kwargs)
    assert exc.value.errors()[0]["type"] == error_type


def test_strict_mode_refuses_coercion() -> None:
    with pytest.raises(ValidationError) as exc:
        Figure(dpi="300")
    assert exc.value.errors()[0]["type"] == "float_type"


def test_figure_size_must_be_positive() -> None:
    for field in ("width_mm", "height_mm", "dpi"):
        with pytest.raises(ValidationError):
            Figure(**{field: 0.0})


@pytest.mark.parametrize("value", [math.inf, math.nan])
def test_sizes_and_ranges_must_be_finite(value: float) -> None:
    with pytest.raises(ValidationError):
        Figure(width_mm=value)
    with pytest.raises(ValidationError):
        Axes(x={"limits": (0.0, value)})


def test_sha256_must_look_like_a_digest() -> None:
    with pytest.raises(ValidationError):
        CsvSource(path="x.csv", sha256="abc")


def test_assignment_is_validated() -> None:
    figure = Figure()
    with pytest.raises(ValidationError):
        figure.dpi = "nope"


def test_unknown_artist_kind_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        Axes.model_validate_json('{"artists": [{"kind": "pie"}]}')
    assert exc.value.errors()[0]["type"] == "union_tag_invalid"


def test_newer_schema_version_is_refused(project: Project) -> None:
    text = dumps(project).replace(
        f'"schema_version": {SCHEMA_VERSION}', '"schema_version": 99', 1
    )
    with pytest.raises(SchemaVersionError, match="schema version 99"):
        loads(text)


def test_older_schema_version_needs_a_migration(project: Project) -> None:
    text = dumps(project).replace(
        f'"schema_version": {SCHEMA_VERSION}', '"schema_version": 0', 1
    )
    with pytest.raises(SchemaVersionError, match="no migration"):
        loads(text)


@pytest.mark.parametrize(
    "text", ["{}", "not json", '{"schema_version": "1"}', '{"schema_version": true}']
)
def test_malformed_project_files_are_refused(text: str) -> None:
    with pytest.raises(SchemaVersionError):
        loads(text)


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_non_finite_floats_roundtrip(value: float, project: Project) -> None:
    # curve_fit reports inf uncertainties when the covariance cannot be
    # estimated; such a project must still load after saving.
    fit = project.figures[0].axes[0].artists[1]
    assert isinstance(fit, FitCurve) and fit.result is not None
    fit.result = fit.result.model_copy(update={"uncertainties": {"a": value}})

    assert loads(dumps(project)) == project


def test_nan_survives_a_roundtrip(project: Project) -> None:
    fit = project.figures[0].axes[0].artists[1]
    assert isinstance(fit, FitCurve) and fit.result is not None
    fit.result = fit.result.model_copy(update={"reduced_chi_square": math.nan})

    loaded = loads(dumps(project)).figures[0].axes[0].artists[1]
    assert isinstance(loaded, FitCurve) and loaded.result is not None
    assert math.isnan(loaded.result.reduced_chi_square)


def test_bin_count_must_be_positive(project: Project) -> None:
    ref = project.figures[0].axes[0].artists[0].x
    with pytest.raises(ValidationError):
        Histogram(values=ref, bins=0)


def test_a_fit_bound_must_be_a_range() -> None:
    from pydantic import ValidationError

    from figscribe.model import FitCurve, PredefinedFit

    model = PredefinedFit(name="linear")
    FitCurve(
        target="t", model=model, parameter_bounds={"a": (None, 1.0), "b": (0.0, None)}
    )
    with pytest.raises(ValidationError, match="lower bound"):
        FitCurve(target="t", model=model, parameter_bounds={"a": (2.0, 1.0)})


def test_a_fit_range_has_a_lower_and_an_upper_end() -> None:
    from pydantic import ValidationError

    from figscribe.model import FitCurve, PredefinedFit

    model = PredefinedFit(name="linear")
    assert FitCurve(target="t", model=model, fit_range=(1.0, 2.0)).fit_range
    with pytest.raises(ValidationError, match="lower end"):
        FitCurve(target="t", model=model, fit_range=(2.0, 1.0))


def test_panel_labels_roundtrip(project: Project) -> None:
    from figscribe.model import PanelLabels

    labels = PanelLabels(style="a)", bold=True, placement="inside", fontsize=9.0)
    project.figures[0].panel_labels = labels
    assert loads(dumps(project)).figures[0].panel_labels == labels
    with pytest.raises(ValidationError):
        PanelLabels(style="i)")
    with pytest.raises(ValidationError):
        PanelLabels(fontsize=0.0)


def test_reference_lines_and_spans_roundtrip(project: Project) -> None:
    from figscribe.model import ReferenceLine, ShadedSpan

    line = ReferenceLine(orientation="horizontal", at=0.5, label="threshold")
    span = ShadedSpan(start=2.0, end=3.5, color="C1")
    project.figures[0].axes[0].artists += [line, span]
    back = loads(dumps(project)).figures[0].axes[0].artists
    assert back[-2:] == [line, span]
    assert isinstance(back[-1], ShadedSpan)
    assert (span.alpha, span.zorder, line.linestyle) == (0.2, 0.5, "--")
    with pytest.raises(ValidationError, match="two different ends"):
        ShadedSpan(start=1.0, end=1.0)
    with pytest.raises(ValidationError, match="two different ends"):
        span.start = 3.5
    with pytest.raises(ValidationError):
        ReferenceLine(at=math.inf)


def test_an_error_band_roundtrips(project: Project) -> None:
    from figscribe.model import ErrorBand

    plot = project.figures[0].axes[0].artists[0]
    plot.band = ErrorBand(color="0.5", alpha=0.4)
    assert loads(dumps(project)).figures[0].axes[0].artists[0].band == plot.band
    with pytest.raises(ValidationError):
        ErrorBand(alpha=1.5)


def test_a_file_without_bands_still_reads() -> None:
    """Files of 0.1.0 have no band field; they read with bars."""
    text = Path(__file__).parents[1] / "examples/gaussian-scan/scan.figscribe"
    plot = loads(text.read_text(encoding="utf-8")).figures[0].axes[0].artists[0]
    assert plot.band is None
